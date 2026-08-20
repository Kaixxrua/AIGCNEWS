package projectsearch

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"math"
	"net"
	"net/http"
	"net/url"
	"sort"
	"strconv"
	"strings"
	"sync"
	"time"
	"unicode"

	"golang.org/x/text/cases"
	"golang.org/x/text/language"
	"golang.org/x/text/unicode/norm"
)

var githubAPIBase = "https://api.github.com"

const (
	fallbackCacheLimit = 128
	fallbackSuccessTTL = 5 * time.Minute
	fallbackEmptyTTL   = 45 * time.Second
	fallbackMinStars   = 500
)

var (
	fallbackFold       = cases.Fold()
	fallbackCacheMu    sync.Mutex
	fallbackCache      = map[string]fallbackCacheEntry{}
	fallbackCacheOrder []string
)

type fallbackCacheEntry struct {
	expires time.Time
	result  FallbackSearchResult
}

type GitHubFallbackConfig struct {
	Enabled        bool
	UseToken       bool
	Token          string
	TimeoutSeconds float64
}

type GitHubFallback struct {
	cfg    GitHubFallbackConfig
	client *http.Client
	now    func() time.Time
}

func NewGitHubFallback(cfg GitHubFallbackConfig) *GitHubFallback {
	t := cfg.TimeoutSeconds
	if t <= 0 {
		t = 8
	}
	connect := t
	if connect > 8 {
		connect = 8
	}
	transport := http.DefaultTransport.(*http.Transport).Clone()
	transport.Proxy = http.ProxyFromEnvironment
	transport.DialContext = (&net.Dialer{Timeout: time.Duration(connect * float64(time.Second))}).DialContext
	transport.TLSHandshakeTimeout = time.Duration(connect * float64(time.Second))
	transport.ResponseHeaderTimeout = time.Duration(t * float64(time.Second))
	return &GitHubFallback{cfg: cfg, client: &http.Client{Transport: transport}, now: time.Now}
}

func (g *GitHubFallback) Search(input FallbackSearchInput) (FallbackSearchResult, error) {
	if !g.cfg.Enabled {
		return FallbackSearchResult{Items: []map[string]any{}, Queries: []string{}, Error: "GitHub fallback is disabled."}, nil
	}
	limit := input.Limit
	if limit <= 0 {
		limit = 10
	}
	if limit > 20 {
		limit = 20
	}
	minStars := input.MinStars
	if minStars < fallbackMinStars {
		minStars = fallbackMinStars
	}
	mode := input.Mode
	if mode == "" {
		mode = "generic"
	}
	if mode != "generic" && mode != "ai" {
		return FallbackSearchResult{}, fmt.Errorf("Unsupported GitHub search mode: %s", mode)
	}
	key := fallbackKey(input, mode, limit, minStars, g.cfg.UseToken && g.cfg.Token != "")
	if result, ok := g.getCache(key); ok {
		result.CacheHit = true
		return result, nil
	}
	queries := buildFallbackQueries(input.Q, input.Category, input.Subcategory, input.Language, minStars, mode)
	if len(queries) == 0 {
		result := FallbackSearchResult{Items: []map[string]any{}, Queries: []string{}, Error: "A concise GitHub search query is required for generic project discovery."}
		g.setCache(key, result)
		return result, nil
	}
	seen := map[string]bool{}
	items := []map[string]any{}
	total := 0
	errors := []string{}
	for _, q := range queries {
		response, err := g.searchOnce(q, input.Sort, limit, true)
		if err != nil {
			errors = append(errors, err.Error())
			continue
		}
		if response.total > total {
			total = response.total
		}
		for _, raw := range response.items {
			if !eligibleStars(raw, minStars) {
				continue
			}
			normalized := normalizeRepo(raw)
			id := strings.ToLower(strings.TrimSpace(stringValue(normalized["full_name"])))
			if id == "" {
				id = strings.ToLower(strings.TrimSpace(fmt.Sprint(normalized["repo_id"])))
			}
			if id == "" || seen[id] {
				continue
			}
			seen[id] = true
			items = append(items, normalized)
		}
	}
	if input.Sort == "updated" {
		sort.SliceStable(items, func(i, j int) bool {
			return strings.ToLower(stringValue(items[i]["full_name"])) < strings.ToLower(stringValue(items[j]["full_name"]))
		})
		sort.SliceStable(items, func(i, j int) bool {
			a, b := stringValue(items[i]["pushed_at"]), stringValue(items[j]["pushed_at"])
			if a != b {
				return a > b
			}
			return intValue(items[i]["stars"]) > intValue(items[j]["stars"])
		})
	} else {
		sort.SliceStable(items, func(i, j int) bool {
			if intValue(items[i]["stars"]) != intValue(items[j]["stars"]) {
				return intValue(items[i]["stars"]) > intValue(items[j]["stars"])
			}
			if intValue(items[i]["forks"]) != intValue(items[j]["forks"]) {
				return intValue(items[i]["forks"]) > intValue(items[j]["forks"])
			}
			return strings.ToLower(stringValue(items[i]["full_name"])) < strings.ToLower(stringValue(items[j]["full_name"]))
		})
	}
	if len(items) > limit {
		items = items[:limit]
	}
	errorText := ""
	if len(errors) > 0 && len(items) == 0 {
		seenErrors := map[string]bool{}
		out := []string{}
		for _, e := range errors {
			if !seenErrors[e] {
				seenErrors[e] = true
				out = append(out, e)
			}
		}
		errorText = strings.Join(out, "; ")
	}
	result := FallbackSearchResult{Items: cloneMaps(items), GitHubTotalCount: total, Queries: append([]string(nil), queries...), Error: errorText}
	g.setCache(key, result)
	return cloneResult(result), nil
}

type githubResponse struct {
	items []map[string]any
	total int
}

func (g *GitHubFallback) searchOnce(query, requestedSort string, limit int, token bool) (githubResponse, error) {
	params := []string{
		"q=" + url.QueryEscape(query),
		"sort=" + url.QueryEscape(fallbackSort(requestedSort)),
		"order=desc", "per_page=" + strconv.Itoa(limit), "page=1",
	}
	req, err := http.NewRequestWithContext(context.Background(), http.MethodGet, githubAPIBase+"/search/repositories?"+strings.Join(params, "&"), nil)
	if err != nil {
		return githubResponse{}, err
	}
	req.Header.Set("Accept", "application/vnd.github+json")
	req.Header.Set("User-Agent", "RAG-AIGC-Agent/1.0")
	req.Header.Set("X-GitHub-Api-Version", "2022-11-28")
	if token && g.cfg.UseToken && strings.TrimSpace(g.cfg.Token) != "" {
		req.Header.Set("Authorization", "Bearer "+g.cfg.Token)
	}
	resp, err := g.client.Do(req)
	if err != nil {
		return githubResponse{}, err
	}
	defer resp.Body.Close()
	if resp.StatusCode == http.StatusUnauthorized && token && g.cfg.UseToken {
		return g.searchOnce(query, requestedSort, limit, false)
	}
	body, readErr := io.ReadAll(resp.Body)
	if readErr != nil {
		return githubResponse{}, readErr
	}
	if resp.StatusCode == http.StatusForbidden || resp.StatusCode == http.StatusTooManyRequests {
		return githubResponse{}, fmt.Errorf("GitHub API rate limited or forbidden: HTTP %d", resp.StatusCode)
	}
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		return githubResponse{}, fmt.Errorf("GitHub API HTTP %d: %s", resp.StatusCode, githubHTTPError(resp.StatusCode, resp.Status, req.URL.String()))
	}
	var payload map[string]any
	dec := json.NewDecoder(strings.NewReader(string(body)))
	dec.UseNumber()
	if err := dec.Decode(&payload); err != nil {
		return githubResponse{}, err
	}
	items := []map[string]any{}
	if raw, ok := payload["items"].([]any); ok {
		for _, v := range raw {
			if m, ok := v.(map[string]any); ok {
				items = append(items, m)
			}
		}
	}
	return githubResponse{items: items, total: intValue(payload["total_count"])}, nil
}

func githubHTTPError(code int, status, target string) string {
	phrase := status
	if i := strings.IndexByte(status, ' '); i >= 0 {
		phrase = status[i+1:]
	}
	kind := "Invalid status code"
	if code >= 100 && code < 200 {
		kind = "Informational response"
	} else if code >= 300 && code < 400 {
		kind = "Redirect response"
	} else if code >= 400 && code < 500 {
		kind = "Client error"
	} else if code >= 500 && code < 600 {
		kind = "Server error"
	}
	return fmt.Sprintf("%s '%d %s' for url '%s'\nFor more information check: https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/%d", kind, code, phrase, target, code)
}

func fallbackSort(sortName string) string {
	if sortName == "updated" || sortName == "recent" {
		return "updated"
	}
	return "stars"
}

func buildFallbackQueries(q, category, subcategory, language string, minStars int, mode string) []string {
	base := fallbackSearchTerms(q, 8)
	if mode == "ai" {
		for _, term := range categoryTerms(category) {
			if !contains(base, term) {
				base = append(base, term)
			}
		}
		for _, term := range fallbackSearchTerms(subcategory, 3) {
			if !contains(base, term) {
				base = append(base, term)
			}
		}
	}
	qualifiers := []string{fmt.Sprintf("stars:>=%d", maxInt(0, minStars))}
	if strings.TrimSpace(language) != "" {
		qualifiers = append(qualifiers, "language:"+strings.TrimSpace(language))
	}
	join := func(parts []string) string {
		all := append(append([]string{}, parts...), qualifiers...)
		return strings.Join(all, " ")
	}
	if mode == "generic" {
		if len(base) == 0 {
			return []string{}
		}
		sets := [][]string{base}
		if len(base) > 4 {
			sets = append(sets, base[:4])
		}
		if len(base) > 3 {
			sets = append(sets, base[len(base)-3:])
		}
		if len(base) > 2 {
			sets = append(sets, base[:2], base[len(base)-2:])
		}
		out := []string{}
		seen := map[string]bool{}
		for _, terms := range sets {
			if len(terms) == 0 {
				continue
			}
			v := join(terms)
			if !seen[v] {
				seen[v] = true
				out = append(out, v)
			}
		}
		return out
	}
	aiTerms := []string{"AI", "LLM", "RAG", "agent", "generative-ai", "mcp", "workflow"}
	primary := base
	if len(primary) == 0 {
		primary = append([]string(nil), aiTerms[:3]...)
	}
	out := []string{join(primary)}
	missing := []string{}
	for _, t := range aiTerms {
		if !contains(primary, t) {
			missing = append(missing, t)
		}
	}
	second := append([]string{}, base...)
	if len(second) > 4 {
		second = second[:4]
	}
	if len(base) == 0 {
		second = append([]string{}, aiTerms[:5]...)
	} else {
		second = append(second, missing[:minInt(3, len(missing))]...)
	}
	out = append(out, join(second))
	dedup := []string{}
	seen := map[string]bool{}
	for _, v := range out {
		v = strings.Join(strings.Fields(v), " ")
		if v != "" && !seen[v] {
			seen[v] = true
			dedup = append(dedup, v)
		}
	}
	return dedup
}

func categoryTerms(category string) []string {
	switch category {
	case "rag_knowledge":
		return []string{"RAG", "knowledge-base", "retrieval-augmented-generation"}
	case "agents_automation":
		return []string{"agent", "mcp", "workflow", "automation"}
	case "coding_tools":
		return []string{"coding", "developer-tools", "code-generation"}
	case "ai_apps":
		return []string{"AI", "chatbot", "web-ui"}
	case "models_infra":
		return []string{"LLM", "model", "inference"}
	case "multimodal_tools":
		return []string{"multimodal", "vision", "image", "audio"}
	case "data_eval_training":
		return []string{"evaluation", "dataset", "training"}
	}
	return nil
}

func fallbackSearchTerms(value string, maxTerms int) []string {
	if maxTerms <= 0 {
		maxTerms = 1
	}
	normalized := normalizeFallback(value)
	blocked := map[string]bool{"github": true, "repo": true, "repository": true, "repositories": true, "project": true, "projects": true, "项目": true, "仓库": true, "工具": true}
	seen := map[string]bool{}
	out := []string{}
	for _, token := range tokenizeFallback(normalized) {
		key := fallbackFold.String(token)
		if blocked[key] || seen[key] {
			continue
		}
		if utf8RuneCount(token) == 1 {
			r, _ := utf8First(token)
			if !unicode.IsDigit(r) {
				continue
			}
		}
		seen[key] = true
		out = append(out, token)
		if len(out) >= maxTerms {
			break
		}
	}
	return out
}
func normalizeFallback(s string) string {
	s = norm.NFKC.String(s)
	return strings.Join(strings.FieldsFunc(strings.TrimFunc(s, pySpace), pySpace), " ")
}
func pySpace(r rune) bool { return unicode.IsSpace(r) || (r >= 0x1c && r <= 0x1f) }
func tokenizeFallback(s string) []string {
	runes := []rune(s)
	out := []string{}
	isASCII := func(r rune) bool { return r >= 'A' && r <= 'Z' || r >= 'a' && r <= 'z' || r >= '0' && r <= '9' }
	isHan := func(r rune) bool { return r >= 0x3400 && r <= 0x4dbf || r >= 0x4e00 && r <= 0x9fff }
	for i := 0; i < len(runes); {
		r := runes[i]
		if isASCII(r) {
			j := i + 1
			for j < len(runes) {
				x := runes[j]
				allowed := isASCII(x) || x == '_' || x == '+' || x == '#' || x == '-'
				if x == '.' && j+1 < len(runes) && isASCII(runes[j+1]) {
					allowed = true
				}
				if !allowed {
					break
				}
				j++
			}
			out = append(out, string(runes[i:j]))
			i = j
			continue
		}
		if r == '.' && i+1 < len(runes) && unicode.IsLetter(runes[i+1]) {
			j := i + 2
			for j < len(runes) && isASCII(runes[j]) {
				j++
			}
			out = append(out, string(runes[i:j]))
			i = j
			continue
		}
		if isHan(r) {
			j := i + 1
			for j < len(runes) && isHan(runes[j]) {
				j++
			}
			out = append(out, string(runes[i:j]))
			i = j
			continue
		}
		i++
	}
	return out
}
func utf8RuneCount(s string) int { return len([]rune(s)) }
func utf8First(s string) (rune, int) {
	for _, r := range s {
		return r, len(string(r))
	}
	return 0, 0
}

func normalizeRepo(item map[string]any) map[string]any {
	full := strings.TrimSpace(stringOr(item["full_name"]))
	if full == "" {
		full = strings.TrimSpace(stringOr(item["name"]))
	}
	topics := []any{}
	if x, ok := item["topics"].([]any); ok {
		topics = x
	}
	if len(topics) > 12 {
		topics = topics[:12]
	}
	lang := strings.TrimSpace(stringOr(item["language"]))
	tags := []any{}
	if lang != "" {
		tags = append(tags, lang)
	}
	for _, t := range topics {
		if len(tags) >= 9 {
			break
		}
		tags = append(tags, fmt.Sprint(t))
	}
	id := item["id"]
	if !truthy(id) {
		id = item["node_id"]
	}
	if !truthy(id) {
		id = full
	}
	lic := ""
	if lm, ok := item["license"].(map[string]any); ok {
		lic = stringOr(lm["spdx_id"])
	}
	stars := intValue(item["stargazers_count"])
	return map[string]any{"id": "github-direct:" + firstNonEmpty(full, fmt.Sprint(item["id"])), "source": "github", "result_origin": "github_api_fallback", "repo_id": id, "website_id": nil, "full_name": full, "title": full, "url": orString(item["html_url"]), "domain": nil, "image_url": nil, "description": orString(item["description"]), "description_zh": "", "category_slug": "", "category_name": "", "subcategory_slug": "", "subcategory_name": "", "tags": tags, "language": lang, "license_spdx_id": lic, "topics": topics, "stars": stars, "forks": intValue(item["forks_count"]), "watchers": intValue(item["subscribers_count"]), "community_metrics_complete": hasKey(item, "subscribers_count"), "open_issues": intValue(item["open_issues_count"]), "created_at": orNil(item["created_at"]), "pushed_at": orNil(item["pushed_at"]), "first_seen_at": nil, "last_seen_at": nil, "last_snapshot_at": nil, "snapshot_date": nil, "rank_in_period": nil, "raw_score": stars, "score": stars, "confidence": 0}
}

func fallbackKey(input FallbackSearchInput, mode string, limit, minStars int, useToken bool) string {
	return strings.Join([]string{mode, fallbackFold.String(normalizeFallback(input.Q)), strings.ToLower(strings.TrimSpace(input.Category)), strings.ToLower(strings.TrimSpace(input.Subcategory)), strings.ToLower(strings.TrimSpace(input.Language)), strings.ToLower(strings.TrimSpace(input.Sort)), strconv.Itoa(limit), strconv.Itoa(minStars), strconv.FormatBool(useToken)}, "\x00")
}
func (g *GitHubFallback) getCache(key string) (FallbackSearchResult, bool) {
	now := g.now()
	fallbackCacheMu.Lock()
	defer fallbackCacheMu.Unlock()
	e, ok := fallbackCache[key]
	if !ok || !e.expires.After(now) {
		if ok {
			delete(fallbackCache, key)
		}
		return FallbackSearchResult{}, false
	}
	return cloneResult(e.result), true
}
func (g *GitHubFallback) setCache(key string, result FallbackSearchResult) {
	ttl := fallbackSuccessTTL
	if len(result.Items) == 0 {
		ttl = fallbackEmptyTTL
	}
	fallbackCacheMu.Lock()
	defer fallbackCacheMu.Unlock()
	if _, ok := fallbackCache[key]; !ok {
		fallbackCacheOrder = append(fallbackCacheOrder, key)
	}
	fallbackCache[key] = fallbackCacheEntry{g.now().Add(ttl), cloneResult(result)}
	for len(fallbackCacheOrder) > fallbackCacheLimit {
		old := fallbackCacheOrder[0]
		fallbackCacheOrder = fallbackCacheOrder[1:]
		delete(fallbackCache, old)
	}
}
func cloneResult(in FallbackSearchResult) FallbackSearchResult {
	out := in
	out.Items = cloneMaps(in.Items)
	out.Queries = append([]string(nil), in.Queries...)
	return out
}
func cloneMaps(in []map[string]any) []map[string]any {
	out := make([]map[string]any, 0, len(in))
	for _, m := range in {
		out = append(out, cloneMap(m))
	}
	return out
}
func cloneMap(in map[string]any) map[string]any {
	out := make(map[string]any, len(in))
	for k, v := range in {
		out[k] = cloneAny(v)
	}
	return out
}
func cloneAny(v any) any {
	switch x := v.(type) {
	case map[string]any:
		return cloneMap(x)
	case []any:
		o := make([]any, len(x))
		for i := range x {
			o[i] = cloneAny(x[i])
		}
		return o
	case []string:
		return append([]string(nil), x...)
	default:
		return v
	}
}
func eligibleStars(item map[string]any, min int) bool {
	s, ok := item["stargazers_count"].(json.Number)
	if ok {
		n, e := s.Int64()
		return e == nil && n >= int64(min)
	}
	if n, ok := item["stargazers_count"].(int); ok {
		return n >= min
	}
	return false
}
func intValue(v any) int {
	switch x := v.(type) {
	case int:
		return x
	case int64:
		return int(x)
	case json.Number:
		n, _ := x.Int64()
		return int(n)
	case float64:
		return int(x)
	case string:
		n, _ := strconv.Atoi(strings.TrimSpace(x))
		return n
	}
	return 0
}
func stringOr(v any) string {
	if s, ok := v.(string); ok {
		return s
	}
	return ""
}
func stringValue(v any) string { return stringOr(v) }
func orString(v any) string {
	if s, ok := v.(string); ok {
		return s
	}
	return ""
}
func orNil(v any) any {
	if truthy(v) {
		return v
	}
	return nil
}
func firstNonEmpty(a, b string) string {
	if a != "" {
		return a
	}
	return b
}
func truthy(v any) bool {
	switch x := v.(type) {
	case nil:
		return false
	case string:
		return x != ""
	case bool:
		return x
	case json.Number:
		return x != "0" && x != ""
	case float64:
		return x != 0
	default:
		return true
	}
}
func hasKey(m map[string]any, k string) bool { _, ok := m[k]; return ok }
func contains(xs []string, x string) bool {
	for _, v := range xs {
		if v == x {
			return true
		}
	}
	return false
}
func maxInt(a, b int) int {
	if a > b {
		return a
	}
	return b
}
func minInt(a, b int) int {
	if a < b {
		return a
	}
	return b
}

var _ = language.Und
var _ = math.IsNaN
