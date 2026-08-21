// Package replay 是黄金语料的 Go 回放门禁：直接消费
// backend/tests/parity/corpus/{protocol,tools}.jsonl，按 corpus_manifest.json
// 的归一化规则逐字节比对 /api/mcp 的响应。
//
// 本包只含测试代码，不进生产二进制。用例纳入范围随 PR 里程碑推进：
//
//   - PR 1.2：信封/解析/认证/通知/错误面 + 无注册表时的 tools/call 错误面；
//   - PR 1.3：限流层落地，rate-limited-429 解除跳过
//     （miniredis + 限额覆盖 + warmup，镜像 recorder.py 的用例编排）；
//   - PR 1.4：tools/list* / resources-list / resources-templates-list /
//     prompts-list（静态清单落地后解除跳过）；
//   - PR 2.2：tools.jsonl 回放 harness 落地，search-papers*/search-documents* /
//     get-project-categories* 11 例解除跳过；文档检索由 fixtures.json
//     documents 段注入 stub 仓储驱动；
//   - PR 2.3：get-paper-detail happy/not-found 两例解除跳过，共享同一
//     fixture 文档仓储与 public projection。
//   - PR 2.4：get_top_items 工具与 resources/read 全路由落地；看板钟与
//     report 日期锚冻结（recorder._frozen_time 双 patch 点的 Go 镜像）；
//     resources.jsonl harness 落地，13 例解除跳过（resource-projects-library
//     依赖 search_github_ai_projects 富化，归 PR 2.8）。
//   - PR 2.5：search_my_project_favorites 落地（身份感知注册缝 +
//     fixtures.json favorites_rows 驱动的 _StubProjectCollections 镜像），
//     favorites-* 6 例解除跳过。
//   - PR 2.6：submit_project_adoption 落地（写路径，无语料用例——
//     recorder 未为本工具录制 stub，门禁为 mcpapp 包 Go 单测）。
//
// 语料新增用例会立即进入回放并以逐字节差异暴露，不允许静默漏测：
// tools.jsonl 每个用例必须在 toolsCorpusMilestones 显式登记归属 PR。
package replay

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"errors"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"regexp"
	"runtime"
	"sort"
	"strconv"
	"strings"
	"testing"
	"time"

	"github.com/alicebob/miniredis/v2"
	"github.com/redis/go-redis/v9"

	"aigcnews/mcp-go/internal/authn"
	"aigcnews/mcp-go/internal/jsonx"
	"aigcnews/mcp-go/internal/mcpapp"
	"aigcnews/mcp-go/internal/ratelimit"
	"aigcnews/mcp-go/internal/version"
)

type corpusCase struct {
	Name   string `json:"name"`
	Replay string `json:"replay"`
	Body   struct {
		Method  string            `json:"method"`
		Path    string            `json:"path"`
		Headers map[string]string `json:"headers"`
		Body    string            `json:"body"`
		BodyB64 string            `json:"body_b64"`
	} `json:"request"`
	Response struct {
		Status  int               `json:"status"`
		Headers map[string]string `json:"headers"`
		Body    string            `json:"body"`
	} `json:"response"`
}

// warmupRequests 镜像 recorder.py ParityCase.warmup：录制前把同一请求
// 原样发送 N 次以预热状态（rate-limited-429 用 warmup=1 消耗掉被压到 1
// 的匿名 tools/call 分钟限额，第二次才录得 429）。
var warmupRequests = map[string]int{
	"rate-limited-429": 1,
}

// sessionIDPattern 与 corpus_manifest.json normalizations 一致。
var sessionIDPattern = regexp.MustCompile(`^aigc-radar-[0-9a-f]{32}$`)

func corpusPath(t *testing.T, name string) string {
	t.Helper()
	_, thisFile, _, ok := runtime.Caller(0)
	if !ok {
		t.Fatal("无法定位 replay 包路径")
	}
	// internal/replay → mcp-go → 仓库根 → backend/tests/parity/corpus
	root := filepath.Dir(filepath.Dir(filepath.Dir(filepath.Dir(thisFile))))
	return filepath.Join(root, "backend", "tests", "parity", "corpus", name)
}

func loadCases(t *testing.T, corpus string) []corpusCase {
	t.Helper()
	raw, err := os.ReadFile(corpusPath(t, corpus))
	if err != nil {
		t.Skipf("parity corpus 不可读（%v），跳过回放", err)
	}
	var cases []corpusCase
	for line := range strings.Lines(string(raw)) {
		line = strings.TrimSpace(line)
		if line == "" {
			continue
		}
		var c corpusCase
		if err := json.Unmarshal([]byte(line), &c); err != nil {
			t.Fatalf("语料行解析失败: %v", err)
		}
		cases = append(cases, c)
	}
	return cases
}

func loadProtocolCases(t *testing.T) []corpusCase {
	return loadCases(t, "protocol.jsonl")
}

// fixtureToken 对齐 fixtures.json tokens 段（recorder._TOKENS 的导出）。
type fixtureToken struct {
	UserID int `json:"user_id"`
	Scopes any `json:"scopes"`
}

// fixtureAuthenticator 复刻 recorder._StubTokenRepository + OptionalMcpUser
// 的判定链：按 SHA-256 反查固定 token 表，scopes 非字符串列表即权限无效。
type fixtureAuthenticator struct {
	tokens map[string]fixtureToken
}

func (f fixtureAuthenticator) Authenticate(_ context.Context, authorization string) (authn.Identity, *authn.Response) {
	if authorization == "" {
		return authn.Identity{}, nil
	}
	if !strings.HasPrefix(strings.ToLower(authorization), "bearer ") {
		return authn.Identity{}, fixtureUnauthorized("Authorization 必须使用 Bearer Token")
	}
	digest := sha256.Sum256([]byte(authorization[len("Bearer "):]))
	entry, ok := f.tokens[hex.EncodeToString(digest[:])]
	if !ok {
		return authn.Identity{}, fixtureUnauthorized("MCP Token 无效、已过期或已撤销")
	}
	scopes, ok := entry.Scopes.([]any)
	if !ok {
		return authn.Identity{}, fixtureUnauthorized("MCP Token 权限无效")
	}
	identity := authn.Identity{UserID: entry.UserID}
	for _, scope := range scopes {
		s, ok := scope.(string)
		if !ok {
			return authn.Identity{}, fixtureUnauthorized("MCP Token 权限无效")
		}
		identity.Scopes = append(identity.Scopes, s)
	}
	return identity, nil
}

func fixtureUnauthorized(detail string) *authn.Response {
	headers := http.Header{}
	headers.Set("WWW-Authenticate", "Bearer")
	return &authn.Response{
		Status:  http.StatusUnauthorized,
		Body:    jsonx.MustMarshalCompact(jsonx.Object{{Key: "detail", Value: detail}}),
		Headers: headers,
	}
}

func loadFixtureAuthenticator(t *testing.T) fixtureAuthenticator {
	t.Helper()
	raw, err := os.ReadFile(corpusPath(t, "fixtures.json"))
	if err != nil {
		t.Skipf("fixtures 不可读（%v），跳过回放", err)
	}
	var fixtures struct {
		Tokens map[string]fixtureToken `json:"tokens"`
	}
	if err := json.Unmarshal(raw, &fixtures); err != nil {
		t.Fatalf("fixtures 解析失败: %v", err)
	}
	byDigest := map[string]fixtureToken{}
	for token, entry := range fixtures.Tokens {
		digest := sha256.Sum256([]byte(token))
		byDigest[hex.EncodeToString(digest[:])] = entry
	}
	return fixtureAuthenticator{tokens: byDigest}
}

// ── 文档 fixture（recorder._StubDocuments 的 Go 镜像） ──────────────────

// fixtureDocuments 复刻 _StubDocuments.search_document_page 的分支表；
// 分页参数被刻意忽略（stub 不按 page/limit 切片，语料分页用例依赖此形态）。
type fixtureDocuments struct {
	arxivA          mcpapp.DocumentRow
	arxivB          mcpapp.DocumentRow
	news            mcpapp.DocumentRow
	oversized       mcpapp.DocumentRow
	channels        map[string][]mcpapp.DocumentRow
	sourceCounts    map[string]int
	todayCount      int
	briefings       map[string]mcpapp.BriefingRecord
	projectSearches map[string]jsonx.Object
	favoritesRows   []map[string]any
	yesterdayHN     map[string]bool
}

type fixtureProjectSearchEngine struct {
	results map[string]jsonx.Object
}

func (f fixtureProjectSearchEngine) SearchProjects(input mcpapp.ProjectSearchInput) (jsonx.Object, error) {
	result, ok := f.results[input.Mode]
	if !ok {
		return nil, errors.New("fixture project search result unavailable")
	}
	return result, nil
}

func (f fixtureDocuments) SearchDocumentPage(query, source string, _, _ int) (mcpapp.DocumentPage, error) {
	switch {
	case query == "oversized":
		return mcpapp.DocumentPage{Items: []mcpapp.DocumentRow{f.oversized}, Total: 1}, nil
	case query == "empty-query":
		return mcpapp.DocumentPage{Items: []mcpapp.DocumentRow{}, Total: 0}, nil
	case strings.ToLower(source) == "news":
		return mcpapp.DocumentPage{Items: []mcpapp.DocumentRow{f.news}, Total: 1}, nil
	default:
		return mcpapp.DocumentPage{Items: []mcpapp.DocumentRow{f.arxivA, f.arxivB}, Total: 17}, nil
	}
}

func (f fixtureDocuments) GetPaperDetail(paperID string) (*mcpapp.DocumentRow, error) {
	if paperID == derefFixtureString(f.arxivA.ID, "") {
		row := f.arxivA
		return &row, nil
	}
	return nil, nil
}

// GetSnapshotDocuments 镜像 recorder._StubRankSnapshots.get_snapshot_documents：
// sourceType/limit 被刻意忽略（stub 不过滤不截断），逐字对齐录制侧。
func (f fixtureDocuments) GetSnapshotDocuments(_, sourceChannel, _ string, _ int) ([]mcpapp.DocumentRow, error) {
	return append([]mcpapp.DocumentRow(nil), f.channels[sourceChannel]...), nil
}

// GetSnapshotDocIDs 镜像 stub：hn_daily_html 恒回昨日 id 集（不区分日期），
// 其余渠道空集。
func (f fixtureDocuments) GetSnapshotDocIDs(_, sourceChannel string) (map[string]bool, error) {
	if sourceChannel == "hn_daily_html" {
		return f.yesterdayHN, nil
	}
	return map[string]bool{}, nil
}

func (f fixtureDocuments) GetSourceCounts() (map[string]int, error) {
	return f.sourceCounts, nil
}

func (f fixtureDocuments) GetTodayDocumentCount() (int, error) {
	return f.todayCount, nil
}

func (f fixtureDocuments) GetBriefing(key string) (*mcpapp.BriefingRecord, error) {
	briefing, ok := f.briefings[key]
	if !ok {
		return nil, nil
	}
	return &briefing, nil
}

// fixtureProjectCollections 复刻 recorder._StubProjectCollections：仅读
// page（page<=1 → 前两行，否则第三行），其余过滤参数刻意忽略，total 恒 3。
// 行原样透传 fixtures.json favorites_rows（UseNumber 解码保留 int/float
// 区分），对齐 Python stub 的 dict 浅拷贝语义（投影链只读不改写）。
type fixtureProjectCollections struct {
	rows []map[string]any
}

func (f fixtureProjectCollections) ListUserProjectCollection(filters mcpapp.ProjectCollectionFilters) (mcpapp.ProjectCollectionPage, error) {
	if filters.Page <= 1 {
		return mcpapp.ProjectCollectionPage{Items: []map[string]any{f.rows[0], f.rows[1]}, Total: 3}, nil
	}
	return mcpapp.ProjectCollectionPage{Items: []map[string]any{f.rows[2]}, Total: 3}, nil
}

func derefFixtureString(value *string, fallback string) string {
	if value == nil {
		return fallback
	}
	return *value
}

// loadFixtureDocuments 把 fixtures.json documents 段转成 DocumentRow。
// 解码用 UseNumber 保留 Python 的 int/float 区分（raw_score 7 int vs 42.5
// float）；created_at 的 {"__type__":"datetime"} 标记转成 Python str(datetime)
// 形状（isoformat 的 "T" 换空格，与 safe_document 的 str() 一致）。
func loadFixtureDocuments(t *testing.T) fixtureDocuments {
	t.Helper()
	raw, err := os.ReadFile(corpusPath(t, "fixtures.json"))
	if err != nil {
		t.Skipf("fixtures 不可读（%v），跳过回放", err)
	}
	var fixtures struct {
		Documents          map[string]map[string]any   `json:"documents"`
		Dashboard          map[string][]map[string]any `json:"dashboard_channels"`
		SourceCounts       map[string]int              `json:"source_counts"`
		TodayCount         int                         `json:"today_document_count"`
		ProjectSearchesRaw json.RawMessage             `json:"project_search_results"`
		FavoritesRows      []map[string]any            `json:"favorites_rows"`
		Briefings          map[string]struct {
			ContentZH string `json:"content_zh"`
			ContentEN string `json:"content_en"`
			Content   string `json:"content"`
		} `json:"briefings"`
		YesterdayHN []string `json:"yesterday_hn_ids"`
	}
	decoder := json.NewDecoder(bytes.NewReader(raw))
	decoder.UseNumber()
	if err := decoder.Decode(&fixtures); err != nil {
		t.Fatalf("fixtures 解析失败: %v", err)
	}
	orderedProjects, err := jsonx.DecodeOrdered(fixtures.ProjectSearchesRaw)
	if err != nil {
		t.Fatalf("fixtures.project_search_results 保序解析失败: %v", err)
	}
	projectSearchesObject, ok := orderedProjects.(jsonx.Object)
	if !ok {
		t.Fatalf("fixtures.project_search_results 类型 = %T，want json object", orderedProjects)
	}
	projectSearches := make(map[string]jsonx.Object, len(projectSearchesObject))
	for _, pair := range projectSearchesObject {
		result, ok := pair.Value.(jsonx.Object)
		if !ok {
			t.Fatalf("fixtures.project_search_results.%s 类型 = %T，want json object", pair.Key, pair.Value)
		}
		projectSearches[pair.Key] = result
	}
	row := func(name string) mcpapp.DocumentRow {
		doc, ok := fixtures.Documents[name]
		if !ok {
			t.Fatalf("fixtures.documents 缺少 %s", name)
		}
		return documentRowFromFixture(t, name, doc)
	}
	channels := map[string][]mcpapp.DocumentRow{}
	for channel, records := range fixtures.Dashboard {
		for i, record := range records {
			channels[channel] = append(channels[channel], documentRowFromFixture(t, channel+"["+strconv.Itoa(i)+"]", record))
		}
	}
	briefings := map[string]mcpapp.BriefingRecord{}
	for key, record := range fixtures.Briefings {
		briefings[key] = mcpapp.BriefingRecord{ContentZH: record.ContentZH, ContentEN: record.ContentEN, Content: record.Content}
	}
	yesterdayHN := map[string]bool{}
	for _, id := range fixtures.YesterdayHN {
		yesterdayHN[id] = true
	}
	return fixtureDocuments{
		arxivA:          row("arxiv_a"),
		arxivB:          row("arxiv_b"),
		news:            row("news"),
		oversized:       row("oversized"),
		channels:        channels,
		sourceCounts:    fixtures.SourceCounts,
		todayCount:      fixtures.TodayCount,
		briefings:       briefings,
		projectSearches: projectSearches,
		favoritesRows:   fixtures.FavoritesRows,
		yesterdayHN:     yesterdayHN,
	}
}

func documentRowFromFixture(t *testing.T, name string, doc map[string]any) mcpapp.DocumentRow {
	t.Helper()
	str := func(key string) *string {
		value, present := doc[key]
		if !present || value == nil {
			return nil
		}
		s, ok := value.(string)
		if !ok {
			t.Fatalf("documents.%s.%s 非字符串: %T", name, key, value)
		}
		return &s
	}
	floatPtr := func(key string) *float64 {
		value, present := doc[key]
		if !present || value == nil {
			return nil
		}
		number, ok := value.(json.Number)
		if !ok {
			t.Fatalf("documents.%s.%s 非数字: %T", name, key, value)
		}
		f, err := number.Float64()
		if err != nil {
			t.Fatalf("documents.%s.%s 浮点解析失败: %v", name, key, err)
		}
		return &f
	}
	row := mcpapp.DocumentRow{
		ID:            str("id"),
		Source:        str("source"),
		SourceChannel: str("source_channel"),
		Title:         str("title"),
		URL:           str("url"),
		Summary:       str("summary"),
		PublishedDate: str("published_date"),
		Tags:          str("tags"),
		Score:         floatPtr("score"),
		RankInPeriod:  int32PtrFromFixture(t, name, doc["rank_in_period"]),
		LocalPDFPath:  str("local_pdf_path"),
		Authors:       str("authors"),
		ArxivID:       str("arxiv_id"),
	}
	// raw_score 保留 int/float 区分（Python 7 int vs 42.5 float）。
	switch value := doc["raw_score"].(type) {
	case nil:
	case json.Number:
		text := value.String()
		if strings.ContainsAny(text, ".eE") {
			f, err := value.Float64()
			if err != nil {
				t.Fatalf("documents.%s.raw_score 浮点解析失败: %v", name, err)
			}
			row.RawScore = f
		} else {
			n, err := value.Int64()
			if err != nil {
				t.Fatalf("documents.%s.raw_score 整数解析失败: %v", name, err)
			}
			row.RawScore = n
		}
	default:
		t.Fatalf("documents.%s.raw_score 非数字: %T", name, value)
	}
	// created_at 的 datetime 标记 → Python str(datetime) 形状。
	switch value := doc["created_at"].(type) {
	case nil:
	case map[string]any:
		if value["__type__"] != "datetime" {
			t.Fatalf("documents.%s.created_at 未知标记: %v", name, value)
		}
		iso, ok := value["value"].(string)
		if !ok {
			t.Fatalf("documents.%s.created_at.value 非字符串: %T", name, value["value"])
		}
		formatted := strings.Replace(iso, "T", " ", 1)
		row.CreatedAt = &formatted
	case string:
		row.CreatedAt = &value
	default:
		t.Fatalf("documents.%s.created_at 类型异常: %T", name, value)
	}
	return row
}

func int32PtrFromFixture(t *testing.T, name string, value any) *int32 {
	t.Helper()
	if value == nil {
		return nil
	}
	number, ok := value.(json.Number)
	if !ok {
		t.Fatalf("documents.%s.rank_in_period 非数字: %T", name, value)
	}
	n, err := number.Int64()
	if err != nil {
		t.Fatalf("documents.%s.rank_in_period 整数解析失败: %v", name, err)
	}
	asInt32 := int32(n)
	return &asInt32
}

func newReplayHandler(t *testing.T, caseName string) http.Handler {
	t.Helper()
	// 对齐 recorder 的 stub 装配：分类走静态仓储，文档检索走 fixtures.json
	// documents 段的 stub（_StubDocuments），PUBLIC_BASE_URL 在录制侧未配置
	// → 空串（pdf_media_url 相对路径 + detail_url/attribution 品牌兜底）。
	registry := mcpapp.Handlers{}
	for name, handler := range mcpapp.NewProjectCategoriesHandlers(mcpapp.StaticProjectCategoriesRepository{}) {
		registry[name] = handler
	}
	documents := loadFixtureDocuments(t)
	for name, handler := range mcpapp.NewDocumentsHandlers(documents, "") {
		registry[name] = handler
	}
	projectSearch := mcpapp.NewProjectSearchService(
		fixtureProjectSearchEngine{results: documents.projectSearches}, "")
	registry["search_github_projects"] = projectSearch.Get
	registry["search_github_ai_projects"] = projectSearch.Search
	for name, handler := range mcpapp.NewPaperDetailHandlers(documents, "") {
		registry[name] = handler
	}
	topItems := mcpapp.NewGetTopItemsService(documents, "")
	registry["get_top_items"] = topItems.Get
	resources := mcpapp.NewResourceService(documents, documents, documents,
		mcpapp.NewProjectCategoriesService(mcpapp.StaticProjectCategoriesRepository{}),
		mcpapp.NewPaperDetailService(documents, ""), "")
	resources.SetProjectLibrary(projectSearch.Search)
	// 冻结时钟，镜像 recorder._frozen_time 的两个独立 patch 点：
	// 看板钟（dashboard_policy.datetime）钉在 CST 2026-08-10 12:00（UTC 瞬
	// 间 +8h 平移后与 policy 的 timezone(timedelta(hours=8)) 同读数）；
	// report/latest 日期锚（application._date.today）钉 2026-08-10。
	frozenNow := func() time.Time { return time.Date(2026, 8, 10, 12, 0, 0, 0, time.UTC) }
	topItems.SetNow(frozenNow)
	resources.SetNow(frozenNow)
	resources.SetToday(func() string { return "2026-08-10" })
	app := mcpapp.New(version.ServerName, version.Fallback, registry)
	app.SetResources(resources)
	// PR 2.5：favorites 走身份感知注册缝；录制侧 PUBLIC_BASE_URL 未配置
	// → 空串，detail_url/attribution 落品牌兜底 https://aigcnews.cn。
	app.RegisterIdentityTool("search_my_project_favorites",
		mcpapp.NewFavoritesService(fixtureProjectCollections{rows: documents.favoritesRows}, "").Get)
	// 对齐 recorder profile 语义：
	// tool_handler_crash → search_papers 处理器抛错；
	// dispatch_crash → 分派阶段 panic（internal-error-500 用例）。
	if caseName == "tool-call-handler-crash" {
		registry["search_papers"] = func(map[string]any) (any, error) {
			return nil, errParityProbe
		}
	}
	if caseName == "internal-error-500" {
		app.PanicOnMethods = map[string]bool{"tools/list": true}
	}
	return mcpapp.NewHandler(app, loadFixtureAuthenticator(t), replayLimiter(t, caseName))
}

// replayLimiter 镜像 recorder 的限流编排：默认不限流（nil，对齐
// FakeRedis 每用例新建=空窗口的多数用例形态）；rate-limited-429 起
// miniredis 并把匿名 tools/call 分钟限额压到 1
// （rate_limit_overrides=(("MCP_ANONYMOUS_TOOL_CALL_LIMIT", 1),)）。
// 可信代理列表置空：httptest 对端 192.0.2.1 直连归因，与语料无 XFF
// 的请求头一致。
func replayLimiter(t *testing.T, caseName string) *ratelimit.Limiter {
	t.Helper()
	if caseName != "rate-limited-429" {
		return nil
	}
	mini := miniredis.RunT(t)
	client := redis.NewClient(&redis.Options{Addr: mini.Addr()})
	t.Cleanup(func() { _ = client.Close() })
	return ratelimit.NewLimiter(ratelimit.GoRedis{Client: client}, "", func(l *ratelimit.Limits) {
		l.AnonymousToolCallPerMinute = 1
	})
}

var errParityProbe = errors.New("parity probe")

// TestProtocolCorpus 逐案回放 protocol.jsonl 的 PR 1.2 范围用例。
func TestProtocolCorpus(t *testing.T) {
	cases := loadProtocolCases(t)
	seen := map[string]bool{}
	for _, c := range cases {
		c := c
		seen[c.Name] = true
		t.Run(c.Name, func(t *testing.T) {
			replayCase(t, c)
		})
	}
	var names []string
	for name := range seen {
		names = append(names, name)
	}
	sort.Strings(names)
	t.Logf("回放通过 %d 例: %s", len(names), strings.Join(names, ", "))
}

func replayCase(t *testing.T, c corpusCase) {
	t.Helper()
	handler := newReplayHandler(t, c.Name)

	var body []byte
	switch {
	case c.Body.BodyB64 != "":
		decoded, err := base64.StdEncoding.DecodeString(c.Body.BodyB64)
		if err != nil {
			t.Fatalf("body_b64 解码失败: %v", err)
		}
		body = decoded
	default:
		body = []byte(c.Body.Body)
	}
	buildRequest := func() *http.Request {
		req := httptest.NewRequest(c.Body.Method, "http://parity.test"+c.Body.Path, bytes.NewReader(body))
		for name, value := range c.Body.Headers {
			req.Header.Set(name, value)
		}
		return req
	}
	// 预热（recorder.py:1203-1204）：录制前原样发送同请求，响应丢弃；
	// 限流用例靠它把窗口计数推到限额边沿。
	for range warmupRequests[c.Name] {
		handler.ServeHTTP(httptest.NewRecorder(), buildRequest())
	}
	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, buildRequest())

	if rec.Code != c.Response.Status {
		t.Errorf("status = %d, want %d\nbody: %s", rec.Code, c.Response.Status, rec.Body.String())
	}
	if got := rec.Body.String(); got != c.Response.Body {
		t.Errorf("body 不一致:\n got %q\nwant %q", got, c.Response.Body)
	}

	got := map[string]string{}
	for name, values := range rec.Header() {
		lower := strings.ToLower(name)
		value := values[0]
		if lower == "mcp-session-id" && sessionIDPattern.MatchString(value) {
			value = "<mcp-session-id>"
		}
		got[lower] = value
	}
	if len(got) != len(c.Response.Headers) {
		t.Errorf("响应头数量 = %d，want %d:\n got %v\nwant %v",
			len(got), len(c.Response.Headers), got, c.Response.Headers)
	}
	for name, want := range c.Response.Headers {
		if value, ok := got[name]; !ok || value != want {
			t.Errorf("header %s = %q, want %q", name, value, want)
		}
	}
}

// TestPromptsCorpus covers prompts/get cases from the frozen prompt corpus.
func TestPromptsCorpus(t *testing.T) {
	cases := loadCases(t, "prompts.jsonl")
	for _, c := range cases {
		c := c
		t.Run(c.Name, func(t *testing.T) { replayCase(t, c) })
	}
}

// ── tools.jsonl 回放（工具语料） ─────────────────────────────────────────

// toolsCorpusMilestones 显式登记 tools.jsonl 每个用例的归属 PR。语料新增
// 用例未登记 → 测试失败（不允许静默漏测）；登记了但语料不存在 → 同样失败
// （防止用例重命名后登记表漂移成僵尸）。
var toolsCorpusMilestones = map[string]string{
	"search-papers":                    "PR 2.2",
	"search-papers-pagination":         "PR 2.2",
	"search-papers-empty":              "PR 2.2",
	"search-papers-oversized":          "PR 2.2",
	"search-papers-missing-q":          "PR 2.2",
	"search-papers-extra-arg":          "PR 2.2",
	"search-documents-all":             "PR 2.2",
	"search-documents-news":            "PR 2.2",
	"search-documents-invalid-source":  "PR 2.2",
	"get-project-categories":           "PR 2.2",
	"get-project-categories-with-args": "PR 2.2",

	"get-paper-detail":           "PR 2.3",
	"get-paper-detail-not-found": "PR 2.3",

	"get-top-items":              "PR 2.4",
	"get-top-items-embargoed":    "PR 2.4",
	"get-top-items-default-date": "PR 2.4",
	"get-top-items-invalid-date": "PR 2.4",
	"get-top-items-weekly":       "PR 2.4",

	"favorites-first-page":            "PR 2.5",
	"favorites-next-page":             "PR 2.5",
	"favorites-anonymous":             "PR 2.5",
	"favorites-no-scope":              "PR 2.5",
	"favorites-bad-marker":            "PR 2.5",
	"favorites-marker-limit-mismatch": "PR 2.5",

	"search-github-projects":       "PR 2.7",
	"search-github-ai-projects":    "PR 2.8",
	"search-github-ai-projects-en": "PR 2.8",
}

// toolsCorpusCurrentMilestone 是本包当前解锁的里程碑。先前 PR 的工具必须继续
// 回放，避免新工具接入使已解锁语料静默失去覆盖；其后用例带里程碑标注跳过。
// PR 2.6 无语料用例（写路径未录制），里程碑仅作进度标注推进。
const toolsCorpusCurrentMilestone = "PR 2.8"

var toolsCorpusMilestoneOrder = []string{
	"PR 2.2", "PR 2.3", "PR 2.4", "PR 2.5", "PR 2.6", "PR 2.7", "PR 2.8",
}

func toolsCorpusMilestoneEnabled(milestone string) bool {
	return toolsCorpusMilestoneEnabledAt(toolsCorpusCurrentMilestone, milestone)
}

func toolsCorpusMilestoneEnabledAt(currentMilestone, milestone string) bool {
	current := -1
	candidate := -1
	for i, value := range toolsCorpusMilestoneOrder {
		if value == currentMilestone {
			current = i
		}
		if value == milestone {
			candidate = i
		}
	}
	return current >= 0 && candidate >= 0 && candidate <= current
}

// TestToolsCorpus 逐案回放 tools.jsonl 中截至当前里程碑的用例。
func TestToolsCorpus(t *testing.T) {
	cases := loadCases(t, "tools.jsonl")
	seen := map[string]bool{}
	for _, c := range cases {
		milestone, registered := toolsCorpusMilestones[c.Name]
		if !registered {
			t.Fatalf("语料用例 %q 未在 toolsCorpusMilestones 登记归属 PR", c.Name)
		}
		seen[c.Name] = true
		c := c
		t.Run(c.Name, func(t *testing.T) {
			if !toolsCorpusMilestoneEnabled(milestone) {
				t.Skipf("归属 %s（当前 %s）", milestone, toolsCorpusCurrentMilestone)
			}
			replayCase(t, c)
		})
	}
	var stale []string
	for name := range toolsCorpusMilestones {
		if !seen[name] {
			stale = append(stale, name)
		}
	}
	if len(stale) > 0 {
		sort.Strings(stale)
		t.Fatalf("登记表含有语料中不存在的用例: %s", strings.Join(stale, ", "))
	}
}

// ── resources.jsonl 回放（资源语料） ─────────────────────────────────────

// resourcesCorpusMilestones 显式登记 resources.jsonl 每个用例的归属 PR，
// 语义与 toolsCorpusMilestones 相同（未登记/僵尸登记均失败）。
// resource-projects-library 依赖 search_github_ai_projects 的 PR 2.8 富化
// （detail_url/data_source/lang），登记 PR 2.8 并在其落地前跳过。
var resourcesCorpusMilestones = map[string]string{
	"resource-dashboard-summary":           "PR 2.4",
	"resource-dashboard-summary-weekly":    "PR 2.4",
	"resource-dashboard-summary-embargoed": "PR 2.4",
	"resource-dashboard-top":               "PR 2.4",
	"resource-projects-categories":         "PR 2.4",
	"resource-projects-library":            "PR 2.8",
	"resource-report-latest-zh":            "PR 2.4",
	"resource-report-latest-en":            "PR 2.4",
	"resource-report-not-found":            "PR 2.4",
	"resource-report-oversized":            "PR 2.4",
	"resource-paper-detail":                "PR 2.4",
	"resource-unknown-uri":                 "PR 2.4",
	"resource-bad-scheme":                  "PR 2.4",
	"resource-missing-uri":                 "PR 2.4",
}

// resourcesCorpusCurrentMilestone 是资源语料当前解锁的里程碑（复用
// toolsCorpusMilestoneOrder 的排序）。
const resourcesCorpusCurrentMilestone = "PR 2.8"

// TestResourcesCorpus 逐案回放 resources.jsonl 中截至当前里程碑的用例。
func TestResourcesCorpus(t *testing.T) {
	cases := loadCases(t, "resources.jsonl")
	seen := map[string]bool{}
	for _, c := range cases {
		milestone, registered := resourcesCorpusMilestones[c.Name]
		if !registered {
			t.Fatalf("语料用例 %q 未在 resourcesCorpusMilestones 登记归属 PR", c.Name)
		}
		seen[c.Name] = true
		c := c
		t.Run(c.Name, func(t *testing.T) {
			if !toolsCorpusMilestoneEnabledAt(resourcesCorpusCurrentMilestone, milestone) {
				t.Skipf("归属 %s（当前 %s）", milestone, resourcesCorpusCurrentMilestone)
			}
			replayCase(t, c)
		})
	}
	var stale []string
	for name := range resourcesCorpusMilestones {
		if !seen[name] {
			stale = append(stale, name)
		}
	}
	if len(stale) > 0 {
		sort.Strings(stale)
		t.Fatalf("登记表含有语料中不存在的用例: %s", strings.Join(stale, ", "))
	}
}
