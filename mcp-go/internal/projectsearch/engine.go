package projectsearch

import (
	"fmt"
	"log/slog"
	"regexp"
	"sort"
	"strings"
	"time"

	"aigcnews/mcp-go/internal/jsonx"
	"aigcnews/mcp-go/internal/mcpapp"
	"aigcnews/mcp-go/internal/projectsem"
)

const ProjectFallbackPolicy = "local_first_github_only_when_semantics_preserved"

var (
	exactRepoQuery     = regexp.MustCompile(`^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$`)
	exactRepoNameQuery = regexp.MustCompile(`^[A-Za-z0-9_.-]+$`)
)

type EngineConfig struct {
	Strategy                    string
	SemanticEnabled             bool
	SemanticHeatFirst           bool
	SemanticQueryTimeoutSeconds float64
	AdoptionWeight              float64
	RerankerEnabled             bool
	RerankerCandidateLimit      int
}

type LexicalCandidateSearchInput struct {
	Q, Scope, Category, Subcategory, Language, Tag string
	MinStars, Limit                                int
	EnrichedOnly                                   bool
}
type LexicalLaneSearchInput struct {
	Plan                                   projectsem.LexicalRetrievalPlan
	Scope, Category, Subcategory, Language string
	MinStars, StrictLimit, RelaxedLimit    int
	EnrichedOnly                           bool
}
type ListProjectsInput struct {
	Source, Scope, Category, Subcategory, Q, Language, Sort string
	Page, PageSize, MinStars                                int
	EnrichedOnly                                            bool
	CandidateRepoIDs                                        []string
}
type CatalogPage struct {
	Items []map[string]any
	Total int
}

type CatalogReader interface {
	FindLexicalCandidateRepoIDs(input LexicalCandidateSearchInput) ([]string, error)
	FindLexicalCandidateLanes(input LexicalLaneSearchInput) (projectsem.LexicalCandidateLanes, error)
	FindRepoIDsByNameSegment(name string, limit int) ([]string, error)
	GetProjectStarsMap(repoIDs []string) (map[string]int, error)
	GetProjectPopularityMap(repoIDs []string) (map[string]Popularity, error)
	ListProjects(input ListProjectsInput) (CatalogPage, error)
}

type FallbackSearchInput struct {
	Q, Category, Subcategory, Language, Sort, Mode string
	Limit, MinStars                                int
}
type FallbackSearchResult struct {
	Items            []map[string]any
	GitHubTotalCount int
	Queries          []string
	Error            string
	CacheHit         bool
}
type FallbackSearcher interface {
	Search(input FallbackSearchInput) (FallbackSearchResult, error)
}

type Engine struct {
	catalog  CatalogReader
	fallback FallbackSearcher
	semantic SemanticSearcher
	reranker Reranker
	cfg      EngineConfig
}

func NewEngine(catalog CatalogReader, fallback FallbackSearcher, semantic SemanticSearcher, reranker Reranker, cfg EngineConfig) (*Engine, error) {
	if catalog == nil {
		return nil, fmt.Errorf("projectsearch: catalog is required")
	}
	cfg.Strategy = resolveStrategy(cfg.Strategy)
	// shadow deliberately keeps the legacy result path authoritative. The
	// Python implementation may submit an out-of-band comparison, but that
	// diagnostic must never block startup or alter the served response. Go uses
	// the same legacy ordering until a comparator is wired in.
	if cfg.SemanticEnabled && semantic == nil {
		return nil, fmt.Errorf("projectsearch: semantic searcher is required when semantic search is enabled")
	}
	if cfg.RerankerEnabled && reranker == nil {
		return nil, fmt.Errorf("projectsearch: reranker is required when reranking is enabled")
	}
	return &Engine{catalog: catalog, fallback: fallback, semantic: semantic, reranker: reranker, cfg: cfg}, nil
}

func resolveStrategy(strategy string) string {
	strategy = strings.ToLower(strings.TrimSpace(strategy))
	if strategy != "legacy" && strategy != "v2" && strategy != "shadow" {
		return "legacy"
	}
	return strategy
}

type searchRequest struct {
	query, mode, language, category, subcategory, scope, effectiveSort, lexicalQuery string
	page, limit, minStars                                                            int
	intent                                                                           projectsem.Intent
	clientIntentUsed                                                                 bool
	plan                                                                             projectsem.LexicalRetrievalPlan
}

func normalizeRequest(input mcpapp.ProjectSearchInput) (searchRequest, error) {
	mode := input.Mode
	if mode != "ai" {
		mode = "generic"
	}
	query := projectsem.NormalizeSearchQuery(input.Query)
	if len([]rune(query)) > 120 {
		query = string([]rune(query)[:120])
	}
	if mode == "generic" && query == "" {
		return searchRequest{}, fmt.Errorf("q is required for generic project search")
	}
	language := clip(strings.TrimSpace(input.Language), 64)
	category, subcategory, scope := "", "", "all"
	if mode == "ai" {
		category = clip(strings.TrimSpace(input.Category), 64)
		subcategory = clip(strings.TrimSpace(input.Subcategory), 64)
		scope = input.Scope
		if scope != "today" && scope != "recommended" && scope != "all" {
			scope = "all"
		}
	}
	sortName := resolveSort(scope, input.Sort, query != "")
	page := input.Page
	if page < 1 {
		page = 1
	}
	limit := input.Limit
	if limit <= 0 {
		limit = 10
	}
	if limit > 20 {
		limit = 20
	}
	intent := projectsem.BuildProjectSearchIntent(query)
	clientUsed := input.ClientIntent != nil && mode == "ai" && query != "" && sortName == "relevance"
	if clientUsed {
		var err error
		intent, err = projectsem.BuildClientProjectSearchIntent(query, *input.ClientIntent)
		if err != nil {
			return searchRequest{}, err
		}
	}
	lexical := strings.Join(intent.LexicalTerms, " ")
	if lexical == "" {
		lexical = intent.NormalizedQuery
	}
	return searchRequest{query: query, mode: mode, language: language, category: category, subcategory: subcategory, scope: scope, effectiveSort: sortName, lexicalQuery: lexical, page: page, limit: limit, minStars: 500, intent: intent, clientIntentUsed: clientUsed, plan: projectsem.BuildProjectLexicalRetrievalPlan(intent)}, nil
}

func resolveSort(scope, requested string, hasQuery bool) string {
	if scope == "today" {
		return "hot"
	}
	switch requested {
	case "relevance", "hot", "stars", "updated", "recent", "name":
		if requested == "relevance" && !hasQuery {
			if scope == "recommended" {
				return "recent"
			}
			return "stars"
		}
		return requested
	}
	if hasQuery {
		return "relevance"
	}
	if scope == "recommended" {
		return "recent"
	}
	return "stars"
}

func (e *Engine) SearchProjects(input mcpapp.ProjectSearchInput) (jsonx.Object, error) {
	r, err := normalizeRequest(input)
	if err != nil {
		return nil, err
	}
	strategy := e.cfg.Strategy
	if strategy == "" {
		strategy = "legacy"
	}
	hybrid := r.query != "" && r.effectiveSort == "relevance"
	var result CatalogPage
	strictEmpty := false
	var ranked []string
	var semanticIDs []string
	var lanes projectsem.LexicalCandidateLanes
	if hybrid {
		if strategy == "v2" {
			lanes, err = e.catalog.FindLexicalCandidateLanes(LexicalLaneSearchInput{Plan: r.plan, Scope: r.scope, Category: r.category, Subcategory: r.subcategory, Language: r.language, MinStars: r.minStars, StrictLimit: 150, RelaxedLimit: 150, EnrichedOnly: true})
			if err != nil {
				slog.Warn("projectsearch lexical lanes failed", "err", err)
				lanes = projectsem.LexicalCandidateLanes{}
			}
			strictEmpty = len(lanes.Strict) == 0
			for _, c := range lanes.Strict {
				ranked = append(ranked, c.RepoID)
			}
		} else {
			var lexical []string
			lexical, err = e.catalog.FindLexicalCandidateRepoIDs(LexicalCandidateSearchInput{Q: r.lexicalQuery, Scope: r.scope, Category: r.category, Subcategory: r.subcategory, Language: r.language, MinStars: r.minStars, Limit: 150, EnrichedOnly: true})
			if err != nil {
				slog.Warn("projectsearch lexical search failed", "err", err)
				lexical = nil
			}
			strictEmpty = len(lexical) == 0
			ranked = append(ranked, lexical...)
		}
		if e.cfg.SemanticEnabled {
			semanticIDs = e.semanticIDs(r.intent.SemanticQueries)
		}
		if strategy == "v2" {
			ranked = e.rankV2(lanes, semanticIDs, r)
		} else {
			ranked = RankLegacyProjectCandidateIDs(ranked, semanticIDs, rankingK, 200)
		}
		if len(ranked) > 0 {
			result, err = e.hydrate(r, ranked, r.page, r.limit)
			if err != nil {
				return nil, err
			}
			if e.cfg.RerankerEnabled && e.reranker != nil {
				result, err = e.applyReranker(r, ranked, result)
				if err != nil {
					return nil, err
				}
			}
		}
	} else {
		result, err = e.catalog.ListProjects(ListProjectsInput{Source: "github", Scope: r.scope, Category: r.category, Subcategory: r.subcategory, Q: r.query, Language: r.language, Page: r.page, PageSize: r.limit, Sort: r.effectiveSort, MinStars: r.minStars, EnrichedOnly: true})
		if err != nil {
			return nil, err
		}
	}
	base := assembleBase(r, result)
	skip := fallbackSkip(r)
	if result.Total > 0 && strictEmpty && r.mode == "generic" && skip == "" && e.fallback != nil {
		return e.runFallback(r, base, "local_low_relevance")
	}
	if result.Total > 0 {
		return base, nil
	}
	if !hybrid && r.query != "" && e.cfg.SemanticEnabled {
		if retried, ok := e.semanticRetry(r, base); ok {
			return retried, nil
		}
	}
	if skip != "" {
		return setObject(base, "fallback_skipped_reason", skip), nil
	}
	if e.fallback == nil {
		return base, nil
	}
	return e.runFallback(r, base, "local_zero_results")
}

func (e *Engine) semanticIDs(queries []string) []string {
	if e.semantic == nil {
		return nil
	}
	timeout := e.cfg.SemanticQueryTimeoutSeconds
	if timeout <= 0 {
		timeout = 6
	}
	ch := make(chan []SemanticHit, 1)
	go func() {
		hits, err := e.semantic.SearchRepoIDs(queries)
		if err != nil {
			ch <- nil
			return
		}
		ch <- hits
	}()
	select {
	case hits := <-ch:
		out := []string{}
		for _, h := range hits {
			if strings.TrimSpace(h.RepoID) != "" {
				out = append(out, h.RepoID)
			}
		}
		return out
	case <-time.After(maxDuration(timeout, 100*time.Millisecond)):
		slog.Warn("projectsearch semantic search timed out")
		return nil
	}
}
func (e *Engine) rankV2(lanes projectsem.LexicalCandidateLanes, semantic []string, r searchRequest) []string {
	exact := ""
	if exactRepoQuery.MatchString(r.query) {
		exact = r.query
	} else if exactRepoNameQuery.MatchString(r.query) {
		if ids, err := e.catalog.FindRepoIDsByNameSegment(r.query, 2); err == nil && len(ids) == 1 {
			exact = ids[0]
		}
	}
	stars := map[string]int{}
	pool := candidatePool(lanes, semantic)
	if e.cfg.AdoptionWeight > 0 {
		if v, err := e.catalog.GetProjectStarsMap(pool); err == nil {
			stars = v
		}
	}
	ranked := RankV2ProjectCandidateIDs(lanes.Strict, lanes.Relaxed, semantic, exact, rankingK, 200, stars, e.cfg.AdoptionWeight)
	if e.cfg.SemanticHeatFirst && !r.clientIntentUsed && len(semantic) > 0 {
		if popularity, err := e.catalog.GetProjectPopularityMap(pool); err == nil && len(popularity) > 0 {
			pinned := []string{}
			for _, c := range lanes.Strict {
				pinned = append(pinned, c.RepoID)
			}
			ranked = OrderCandidatesByPopularity(ranked, popularity, exact, pinned)
		}
	}
	return ranked
}
func candidatePool(l projectsem.LexicalCandidateLanes, s []string) []string {
	seen := map[string]bool{}
	out := []string{}
	for _, c := range l.Strict {
		if !seen[c.RepoID] {
			seen[c.RepoID] = true
			out = append(out, c.RepoID)
		}
	}
	for _, c := range l.Relaxed {
		if !seen[c.RepoID] {
			seen[c.RepoID] = true
			out = append(out, c.RepoID)
		}
	}
	for _, id := range s {
		if !seen[id] {
			seen[id] = true
			out = append(out, id)
		}
	}
	return out
}
func (e *Engine) hydrate(r searchRequest, ids []string, page, size int) (CatalogPage, error) {
	return e.catalog.ListProjects(ListProjectsInput{Source: "github", Scope: r.scope, Category: r.category, Subcategory: r.subcategory, Language: r.language, Page: page, PageSize: size, Sort: "relevance", MinStars: r.minStars, EnrichedOnly: true, CandidateRepoIDs: ids})
}

func (e *Engine) applyReranker(r searchRequest, ids []string, initial CatalogPage) (CatalogPage, error) {
	candidateLimit := e.cfg.RerankerCandidateLimit
	if candidateLimit <= 0 {
		candidateLimit = 20
	}
	rerankLimit := candidateLimit
	if rerankLimit > 20 {
		rerankLimit = 20
	}
	if rerankLimit < r.limit {
		rerankLimit = r.limit
	}
	prefix, err := e.hydrate(r, ids, 1, rerankLimit)
	if err != nil {
		return initial, err
	}
	projects := append([]map[string]any(nil), prefix.Items...)
	ranked := e.reranker.RerankRepoIDs(rerankerQuery(r), projects)
	seen := map[string]bool{}
	ordered := make([]string, 0, len(ranked)+len(ids))
	for _, id := range ranked {
		id = strings.TrimSpace(id)
		if id != "" && !seen[id] {
			seen[id] = true
			ordered = append(ordered, id)
		}
	}
	for _, id := range ids {
		if !seen[id] {
			seen[id] = true
			ordered = append(ordered, id)
		}
	}
	if len(ordered) == 0 {
		return initial, nil
	}
	return e.hydrate(r, ordered, r.page, r.limit)
}

func (e *Engine) semanticRetry(r searchRequest, base jsonx.Object) (jsonx.Object, bool) {
	ids := e.semanticIDs(r.intent.SemanticQueries)
	if len(ids) == 0 {
		return nil, false
	}
	page, err := e.hydrate(r, ids, r.page, r.limit)
	if err != nil || page.Total <= 0 {
		return nil, false
	}
	out := setObject(base, "items", publicItems(page.Items))
	out = setObject(out, "total", page.Total)
	out = setObject(out, "local_total", page.Total)
	out = setObject(out, "has_next", r.page*r.limit < page.Total)
	return out, true
}

func assembleBase(r searchRequest, page CatalogPage) jsonx.Object {
	total := page.Total
	return jsonx.Object{{Key: "items", Value: publicItems(page.Items)}, {Key: "total", Value: total}, {Key: "page", Value: r.page}, {Key: "page_size", Value: r.limit}, {Key: "has_next", Value: r.page*r.limit < total}, {Key: "min_stars", Value: r.minStars}, {Key: "scope", Value: r.scope}, {Key: "category", Value: r.category}, {Key: "subcategory", Value: r.subcategory}, {Key: "language", Value: r.language}, {Key: "q", Value: r.query}, {Key: "sort", Value: r.effectiveSort}, {Key: "source", Value: "github"}, {Key: "search_mode", Value: r.mode}, {Key: "result_origin", Value: "aigc_news_local"}, {Key: "local_total", Value: total}, {Key: "fallback_used", Value: false}, {Key: "fallback_reason", Value: ""}, {Key: "fallback_skipped_reason", Value: ""}, {Key: "fallback_policy", Value: ProjectFallbackPolicy}}
}
func publicItems(items []map[string]any) []any {
	out := make([]any, 0, len(items))
	for _, item := range items {
		out = append(out, mcpapp.PublicProjectItem(item))
	}
	return out
}
func setObject(obj jsonx.Object, key string, value any) jsonx.Object {
	out := append(jsonx.Object(nil), obj...)
	for i := range out {
		if out[i].Key == key {
			out[i].Value = value
			return out
		}
	}
	return append(out, jsonx.Pair{Key: key, Value: value})
}
func fallbackSkip(r searchRequest) string {
	if r.page != 1 {
		return "fallback_is_first_page_only"
	}
	if r.scope != "all" {
		return "scope_requires_local_metrics"
	}
	if r.category != "" || r.subcategory != "" {
		return "taxonomy_filter_requires_local_classification"
	}
	if r.effectiveSort != "relevance" && r.effectiveSort != "stars" && r.effectiveSort != "updated" {
		return "sort_not_equivalent_on_github_search"
	}
	return ""
}
func (e *Engine) runFallback(r searchRequest, base jsonx.Object, reason string) (jsonx.Object, error) {
	sortName := r.effectiveSort
	if sortName == "relevance" {
		sortName = "stars"
	}
	result, err := e.fallback.Search(FallbackSearchInput{Q: r.query, Language: r.language, Sort: sortName, Limit: r.limit, MinStars: r.minStars, Mode: r.mode})
	if err != nil {
		out := setObject(base, "fallback_used", true)
		out = setObject(out, "fallback_reason", reason)
		return append(out, jsonx.Pair{Key: "fallback_error", Value: "GitHub fallback failed: " + err.Error()}), nil
	}
	items := publicItems(result.Items)
	out := setObject(base, "items", items)
	out = setObject(out, "total", len(items))
	out = setObject(out, "has_next", false)
	out = setObject(out, "result_origin", func() string {
		if len(items) > 0 {
			return "github_api_fallback"
		}
		return "aigc_news_local"
	}())
	out = setObject(out, "fallback_used", true)
	out = setObject(out, "fallback_reason", reason)
	out = append(out, jsonx.Pair{Key: "fallback_error", Value: result.Error}, jsonx.Pair{Key: "github_total_count", Value: result.GitHubTotalCount}, jsonx.Pair{Key: "fallback_queries", Value: result.Queries}, jsonx.Pair{Key: "fallback_cache_hit", Value: result.CacheHit})
	return out, nil
}

func clip(s string, n int) string {
	r := []rune(s)
	if len(r) <= n {
		return s
	}
	if n <= 1 {
		return string(r[:n])
	}
	return strings.TrimRight(string(r[:n-1]), " ") + "…"
}
func maxDuration(a float64, b time.Duration) time.Duration {
	d := time.Duration(a * float64(time.Second))
	if d < b {
		return b
	}
	return d
}
func rerankerQuery(r searchRequest) string {
	parts := []string{r.query}
	if r.clientIntentUsed {
		if r.intent.IntentClass != "" {
			parts = append(parts, "intent: "+r.intent.IntentClass)
		}
		if len(r.intent.Topics) > 0 {
			parts = append(parts, "topics: "+strings.Join(r.intent.Topics, ", "))
		}
		if len(r.intent.ArtifactTypes) > 0 {
			parts = append(parts, "artifact types: "+strings.Join(r.intent.ArtifactTypes, ", "))
		}
		if len(r.intent.MustHave) > 0 {
			parts = append(parts, "must have: "+strings.Join(r.intent.MustHave, ", "))
		}
		if len(r.intent.ShouldHave) > 0 {
			parts = append(parts, "should have: "+strings.Join(r.intent.ShouldHave, ", "))
		}
	}
	return clip(strings.Join(parts, "; "), 500)
}

var _ = rerankerQuery
var _ = sort.Strings
