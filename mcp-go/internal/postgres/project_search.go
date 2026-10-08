package postgres

// project_search.go implements the PostgreSQL read side used by the generic
// project search engine.  The SQL is intentionally kept close to
// postgres_project_catalog.py: the query planner and ranking policy live in
// internal/projectsearch, while this adapter only performs candidate recall,
// page hydration, and metric lookups.

import (
	"context"
	"fmt"
	"strconv"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"

	"aigcnews/mcp-go/internal/projectsearch"
	"aigcnews/mcp-go/internal/projectsem"
)

const projectSearchMinStars = 500

// ProjectSearchRepository is the production CatalogReader implementation.
type ProjectSearchRepository struct {
	pool                   *pgxpool.Pool
	timezone               string
	statementTimeoutMillis int
}

// NewProjectSearchRepository keeps the original two-argument constructor
// usable while allowing production callers to pass the same per-read timeout
// as the Python catalog repository. A timeout omitted by legacy callers leaves
// the pool-level setting in control; an explicitly non-positive value is
// clamped to one millisecond, matching the Python repository.
func NewProjectSearchRepository(pool *pgxpool.Pool, timezone string, statementTimeoutMillis ...int) *ProjectSearchRepository {
	if timezone == "" {
		timezone = "Asia/Shanghai"
	}
	timeout := 0
	if len(statementTimeoutMillis) > 0 {
		timeout = statementTimeoutMillis[0]
		if timeout < 1 {
			timeout = 1
		}
	}
	return &ProjectSearchRepository{
		pool:                   pool,
		timezone:               timezone,
		statementTimeoutMillis: timeout,
	}
}

var projectSearchTermFields = ghTermMatchFieldsWithI18nTags[:7]

var projectSearchStrongTermFields = []string{
	"c.full_name",
	"c.title",
	"COALESCE(ge.tags_json::text, '')",
	"COALESCE(ge.tags_zh_json::text, '')",
	"COALESCE(ge.tags_en_json::text, '')",
}

const projectSearchRelevanceStrongMatchThreshold = 5

func projectSearchTermFilter() string {
	return projectSearchTermFilterForFields(projectSearchTermFields)
}

func projectSearchTermFilterForFields(fields []string) string {
	parts := make([]string, len(fields))
	for i, field := range fields {
		parts[i] = field + " ILIKE %s ESCAPE '='"
	}
	return "(" + strings.Join(parts, " OR ") + ")"
}

func clampProjectSearchLimit(value, fallback, maximum int) int {
	if value == 0 {
		value = fallback
	}
	if value < 1 {
		value = 1
	}
	if value > maximum {
		value = maximum
	}
	return value
}

func (r *ProjectSearchRepository) beginRead(ctx context.Context) (pgx.Tx, error) {
	if r == nil || r.pool == nil {
		return nil, fmt.Errorf("postgres: project search pool is nil")
	}
	tx, err := r.pool.BeginTx(ctx, pgx.TxOptions{IsoLevel: pgx.RepeatableRead, AccessMode: pgx.ReadOnly})
	if err != nil {
		return nil, err
	}
	if r.statementTimeoutMillis == 0 {
		return tx, nil
	}
	if _, err := tx.Exec(ctx, "SELECT set_config('statement_timeout', $1, true)", strconv.Itoa(r.statementTimeoutMillis)); err != nil {
		_ = tx.Rollback(ctx)
		return nil, fmt.Errorf("postgres: project search statement timeout: %w", err)
	}
	return tx, nil
}

func projectSearchRows(rows pgx.Rows) ([]map[string]any, error) {
	defer rows.Close()
	fields := rows.FieldDescriptions()
	items := make([]map[string]any, 0)
	for rows.Next() {
		values, err := rows.Values()
		if err != nil {
			return nil, err
		}
		item := make(map[string]any, len(fields))
		for i, field := range fields {
			item[string(field.Name)] = values[i]
		}
		// The strong-match marker is an internal SQL helper and is not part of
		// normalize_project_row's public row shape.
		delete(item, "has_strong_match")
		items = append(items, normalizeProjectRow(item))
	}
	if err := rows.Err(); err != nil {
		return nil, err
	}
	return items, nil
}

func (r *ProjectSearchRepository) FindLexicalCandidateRepoIDs(input projectsearch.LexicalCandidateSearchInput) ([]string, error) {
	terms := projectSearchTerms(input.Q)
	if len(terms) == 0 {
		return []string{}, nil
	}
	limit := clampProjectSearchLimit(input.Limit, 200, 200)
	minStars := input.MinStars
	if minStars <= 0 {
		minStars = projectSearchMinStars
	}
	normalizedQuery := normalizeSearchQuery(input.Q)

	filters := []string{"COALESCE(c.stars, 0) >= %s", "ga.alias_repo_id IS NULL"}
	params := []any{minStars}
	if input.EnrichedOnly {
		filters = append(filters, "ge.status = 'succeeded'", ghQuarantineFilter)
	}
	if input.Scope == "recommended" {
		filters = append(filters, "EXISTS (SELECT 1 FROM github_repo_recommendations gr WHERE gr.repo_id = c.repo_id AND gr.active = TRUE)")
	}
	if input.Category != "" {
		filters = append(filters, "ge.category_slug = %s")
		params = append(params, input.Category)
	}
	if input.Subcategory != "" {
		if defaultSub, ok := ghDefaultSubcategoryByCategory[input.Category]; ok && input.Subcategory == defaultSub {
			filters = append(filters, "(ge.subcategory_slug = %s OR COALESCE(ge.subcategory_slug, '') = '')")
		} else {
			filters = append(filters, "ge.subcategory_slug = %s")
		}
		params = append(params, input.Subcategory)
	}
	if input.Language != "" {
		filters = append(filters, "LOWER(COALESCE(c.language, '')) = LOWER(%s)")
		params = append(params, input.Language)
	}
	if strings.TrimSpace(input.Tag) != "" {
		filters = append(filters, "COALESCE(ge.tags_json::text, '') ILIKE %s")
		params = append(params, "%\""+strings.TrimSpace(input.Tag)+"\"%")
	}
	termFilter := projectSearchTermFilter()
	for _, term := range terms {
		like := "%" + escapeLikeLiteral.Replace(term) + "%"
		filters = append(filters, termFilter)
		for range projectSearchTermFields {
			params = append(params, like)
		}
	}
	prefix := escapeLikeLiteral.Replace(strings.Join(strings.Fields(input.Q), " ")) + "%"
	query := fmt.Sprintf(`SELECT c.repo_id FROM github_repo_candidates c
            LEFT JOIN github_repo_enrichments ge ON ge.repo_id=c.repo_id
            LEFT JOIN github_repo_aliases ga ON ga.alias_repo_id=c.repo_id AND ga.canonical_repo_id<>c.repo_id
            WHERE %s
            ORDER BY CASE WHEN LOWER(c.full_name)=LOWER(%%s) THEN 0 WHEN LOWER(split_part(c.full_name,'/',2))=LOWER(%%s) THEN 1 WHEN LOWER(COALESCE(c.title,''))=LOWER(%%s) THEN 2 WHEN split_part(c.full_name,'/',2) ILIKE %%s ESCAPE '=' THEN 3 WHEN c.full_name ILIKE %%s ESCAPE '=' THEN 4 WHEN COALESCE(c.title,'') ILIKE %%s ESCAPE '=' THEN 5 ELSE 6 END,
                COALESCE(c.stars,0) DESC,c.repo_id COLLATE "C" ASC LIMIT %%s`, strings.Join(filters, " AND "))
	params = append(params, normalizedQuery, normalizedQuery, normalizedQuery, prefix, prefix, prefix, limit)

	ctx := context.Background()
	tx, err := r.beginRead(ctx)
	if err != nil {
		return nil, fmt.Errorf("postgres: lexical candidate transaction: %w", err)
	}
	defer func() { _ = tx.Rollback(ctx) }()
	rows, err := tx.Query(ctx, dollarPlaceholders(query), params...)
	if err != nil {
		return nil, fmt.Errorf("postgres: lexical candidate query: %w", err)
	}
	defer rows.Close()
	ids := make([]string, 0)
	for rows.Next() {
		values, err := rows.Values()
		if err != nil {
			return nil, fmt.Errorf("postgres: lexical candidate row: %w", err)
		}
		if len(values) > 0 {
			if id, ok := values[0].(string); ok && id != "" {
				ids = append(ids, id)
			}
		}
	}
	if err := rows.Err(); err != nil {
		return nil, fmt.Errorf("postgres: lexical candidate rows: %w", err)
	}
	if err := tx.Commit(ctx); err != nil {
		return nil, fmt.Errorf("postgres: lexical candidate commit: %w", err)
	}
	return ids, nil
}

func (r *ProjectSearchRepository) FindLexicalCandidateLanes(input projectsearch.LexicalLaneSearchInput) (projectsem.LexicalCandidateLanes, error) {
	plan := input.Plan
	normalizedQuery := normalizeSearchQuery(plan.NormalizedQuery)
	strictTerms := make([]string, 0, len(plan.StrictTerms))
	for _, term := range plan.StrictTerms {
		if strings.TrimSpace(term) != "" {
			strictTerms = append(strictTerms, strings.TrimSpace(term))
		}
	}
	concepts := make([]projectsem.LexicalConcept, 0, len(plan.Concepts))
	for _, concept := range plan.Concepts {
		seen := map[string]bool{}
		terms := make([]string, 0, len(concept.PrimaryTerms)+len(concept.Aliases))
		for _, term := range append(append([]string{}, concept.PrimaryTerms...), concept.Aliases...) {
			term = strings.TrimSpace(term)
			if term != "" && !seen[term] {
				seen[term] = true
				terms = append(terms, term)
			}
		}
		if len(terms) > 0 {
			concepts = append(concepts, projectsem.LexicalConcept{ConceptID: concept.ConceptID, PrimaryTerms: terms[:minProjectSearchInt(1, len(terms))], Aliases: terms[minProjectSearchInt(1, len(terms)):]})
		}
	}
	requiredCoverage := len(strictTerms) + len(concepts)
	if requiredCoverage == 0 {
		return projectsem.LexicalCandidateLanes{Strict: []projectsem.LexicalCandidate{}, Relaxed: []projectsem.LexicalCandidate{}}, nil
	}
	strictLimit := clampProjectSearchLimit(input.StrictLimit, 150, 150)
	relaxedLimit := clampProjectSearchLimit(input.RelaxedLimit, 150, 150)
	minStars := input.MinStars
	if minStars <= 0 {
		minStars = projectSearchMinStars
	}
	filters := []string{"COALESCE(c.stars, 0) >= %s"}
	filterParams := []any{minStars}
	if input.EnrichedOnly {
		filters = append(filters, "ge.status = 'succeeded'", ghQuarantineFilter)
	}
	if input.Scope == "recommended" {
		filters = append(filters, "EXISTS (SELECT 1 FROM github_repo_recommendations gr WHERE gr.repo_id = c.repo_id AND gr.active = TRUE)")
	}
	if input.Category != "" {
		filters = append(filters, "ge.category_slug = %s")
		filterParams = append(filterParams, input.Category)
	}
	if input.Subcategory != "" {
		if defaultSub, ok := ghDefaultSubcategoryByCategory[input.Category]; ok && input.Subcategory == defaultSub {
			filters = append(filters, "(ge.subcategory_slug = %s OR COALESCE(ge.subcategory_slug, '') = '')")
		} else {
			filters = append(filters, "ge.subcategory_slug = %s")
		}
		filterParams = append(filterParams, input.Subcategory)
	}
	if input.Language != "" {
		filters = append(filters, "LOWER(COALESCE(c.language, '')) = LOWER(%s)")
		filterParams = append(filterParams, input.Language)
	}
	filters = append(filters, "NOT EXISTS (SELECT 1 FROM github_repo_aliases ga WHERE ga.alias_repo_id = c.repo_id AND ga.canonical_repo_id <> c.repo_id)")

	candidateDocument := "LOWER(COALESCE(c.full_name, '') || ' ' || COALESCE(c.title, '') || ' ' || COALESCE(c.description, '') || ' ' || COALESCE(c.language, '') || ' ' || COALESCE(c.topics_json, ''))"
	enrichmentDocument := "LOWER(COALESCE(ge.description_zh, '') || ' ' || COALESCE(ge.tags_json::text, ''))"
	type hit struct {
		group, pattern string
		isConcept      bool
	}
	hits := make([]hit, 0)
	for i, term := range strictTerms {
		hits = append(hits, hit{fmt.Sprintf("term:%d", i), "%" + escapeLikeLiteral.Replace(term) + "%", false})
	}
	for _, concept := range concepts {
		terms := append(append([]string{}, concept.PrimaryTerms...), concept.Aliases...)
		for _, term := range terms {
			hits = append(hits, hit{"concept:" + concept.ConceptID, projectsem.ConceptSearchPattern(term), true})
		}
	}
	groups := make([]string, 0, len(hits))
	seenGroups := map[string]bool{}
	for _, h := range hits {
		if !seenGroups[h.group] {
			seenGroups[h.group] = true
			groups = append(groups, h.group)
		}
	}
	branches := make([]string, 0, len(hits)*2)
	hitParams := make([]any, 0, len(hits)*4)
	for _, h := range hits {
		predicate := "ILIKE %s ESCAPE '='"
		if h.isConcept {
			predicate = "~* %s"
		}
		branches = append(branches,
			fmt.Sprintf("SELECT c.repo_id, %%s::text AS group_id FROM github_repo_candidates c JOIN eligible e ON e.repo_id = c.repo_id WHERE %s %s", candidateDocument, predicate),
			fmt.Sprintf("SELECT ge.repo_id, %%s::text AS group_id FROM github_repo_enrichments ge JOIN eligible e ON e.repo_id = ge.repo_id WHERE %s %s", enrichmentDocument, predicate),
		)
		hitParams = append(hitParams, h.group, h.pattern, h.group, h.pattern)
	}
	prefix := escapeLikeLiteral.Replace(normalizedQuery) + "%"
	query := fmt.Sprintf(`WITH eligible AS MATERIALIZED (
                SELECT c.repo_id, c.full_name, c.title, COALESCE(c.stars, 0) AS stars
                FROM github_repo_candidates c
                LEFT JOIN github_repo_enrichments ge ON ge.repo_id = c.repo_id
                WHERE %s
            ), raw_hits AS MATERIALIZED (
                SELECT DISTINCT repo_id, group_id
                FROM (%s) branch_hits
            ), scored AS MATERIALIZED (
                SELECT e.repo_id, e.full_name, e.stars, COUNT(*)::integer AS term_coverage,
                    CASE WHEN LOWER(e.full_name) = LOWER(%%s) THEN 6 WHEN LOWER(split_part(e.full_name, '/', 2)) = LOWER(%%s) THEN 5 WHEN LOWER(COALESCE(e.title, '')) = LOWER(%%s) THEN 4 WHEN split_part(e.full_name, '/', 2) ILIKE %%s ESCAPE '=' THEN 3 WHEN e.full_name ILIKE %%s ESCAPE '=' THEN 2 WHEN COALESCE(e.title, '') ILIKE %%s ESCAPE '=' THEN 1 ELSE 0 END AS match_strength
                FROM raw_hits hit JOIN eligible e ON e.repo_id = hit.repo_id
                GROUP BY e.repo_id, e.full_name, e.title, e.stars
            ), bounded_lanes AS (
                (SELECT 'strict'::text AS lane, 0 AS lane_order, repo_id, term_coverage, match_strength, stars, full_name FROM scored WHERE term_coverage = %%s ORDER BY match_strength DESC, stars DESC, repo_id COLLATE "C" ASC LIMIT %%s)
                UNION ALL
                (SELECT 'relaxed'::text AS lane, 1 AS lane_order, repo_id, term_coverage, match_strength, stars, full_name FROM scored WHERE term_coverage > 0 ORDER BY term_coverage DESC, match_strength DESC, stars DESC, repo_id COLLATE "C" ASC LIMIT %%s)
            )
            SELECT lane, repo_id, term_coverage, match_strength FROM bounded_lanes
            ORDER BY lane_order, CASE WHEN lane_order = 1 THEN term_coverage END DESC, match_strength DESC, stars DESC, repo_id COLLATE "C" ASC`, strings.Join(filters, " AND "), strings.Join(branches, " UNION ALL "))
	params := append([]any{}, filterParams...)
	params = append(params, hitParams...)
	params = append(params, normalizedQuery, normalizedQuery, normalizedQuery, prefix, prefix, prefix, len(groups), strictLimit, relaxedLimit)

	ctx := context.Background()
	tx, err := r.beginRead(ctx)
	if err != nil {
		return projectsem.LexicalCandidateLanes{}, fmt.Errorf("postgres: lexical lanes transaction: %w", err)
	}
	defer func() { _ = tx.Rollback(ctx) }()
	rows, err := tx.Query(ctx, dollarPlaceholders(query), params...)
	if err != nil {
		return projectsem.LexicalCandidateLanes{}, fmt.Errorf("postgres: lexical lanes query: %w", err)
	}
	defer rows.Close()
	lanes := projectsem.LexicalCandidateLanes{Strict: []projectsem.LexicalCandidate{}, Relaxed: []projectsem.LexicalCandidate{}}
	for rows.Next() {
		values, err := rows.Values()
		if err != nil {
			return projectsem.LexicalCandidateLanes{}, fmt.Errorf("postgres: lexical lanes row: %w", err)
		}
		if len(values) < 4 {
			continue
		}
		lane, _ := values[0].(string)
		repoID, _ := values[1].(string)
		coverage := intOrZero(values[2])
		strength := intOrZero(values[3])
		candidate := projectsem.LexicalCandidate{RepoID: repoID, Lane: lane, TermCoverage: coverage, MatchStrength: strength}
		if repoID == "" {
			continue
		}
		if lane == "strict" {
			lanes.Strict = append(lanes.Strict, candidate)
		} else if lane == "relaxed" {
			lanes.Relaxed = append(lanes.Relaxed, candidate)
		}
	}
	if err := rows.Err(); err != nil {
		return projectsem.LexicalCandidateLanes{}, fmt.Errorf("postgres: lexical lanes rows: %w", err)
	}
	if err := tx.Commit(ctx); err != nil {
		return projectsem.LexicalCandidateLanes{}, fmt.Errorf("postgres: lexical lanes commit: %w", err)
	}
	return lanes, nil
}

func (r *ProjectSearchRepository) FindRepoIDsByNameSegment(name string, limit int) ([]string, error) {
	normalized := strings.TrimSpace(strings.Join(strings.Fields(name), " "))
	if normalized == "" {
		return []string{}, nil
	}
	limit = clampProjectSearchLimit(limit, 2, 10)
	query := `SELECT c.repo_id FROM github_repo_candidates c
            WHERE LOWER(split_part(c.full_name, '/', 2)) = LOWER(%s)
              AND c.availability_status = 'active'
              AND NOT EXISTS (SELECT 1 FROM github_repo_aliases ga
                              WHERE ga.alias_repo_id = c.repo_id
                              AND ga.canonical_repo_id <> c.repo_id)
              AND NOT EXISTS (SELECT 1 FROM github_repo_quarantine gq
                              WHERE gq.repo_id = c.repo_id)
            ORDER BY COALESCE(c.stars, 0) DESC, c.repo_id COLLATE "C" ASC
            LIMIT %s`
	ctx := context.Background()
	tx, err := r.beginRead(ctx)
	if err != nil {
		return nil, fmt.Errorf("postgres: repository name transaction: %w", err)
	}
	defer func() { _ = tx.Rollback(ctx) }()
	rows, err := tx.Query(ctx, dollarPlaceholders(query), normalized, limit)
	if err != nil {
		return nil, fmt.Errorf("postgres: repository name query: %w", err)
	}
	defer rows.Close()
	ids := []string{}
	for rows.Next() {
		values, err := rows.Values()
		if err != nil {
			return nil, fmt.Errorf("postgres: repository name row: %w", err)
		}
		if len(values) > 0 {
			if id, ok := values[0].(string); ok && id != "" {
				ids = append(ids, id)
			}
		}
	}
	if err := rows.Err(); err != nil {
		return nil, fmt.Errorf("postgres: repository name rows: %w", err)
	}
	if err := tx.Commit(ctx); err != nil {
		return nil, fmt.Errorf("postgres: repository name commit: %w", err)
	}
	return ids, nil
}

func (r *ProjectSearchRepository) GetProjectStarsMap(repoIDs []string) (map[string]int, error) {
	ids := cleanProjectRepoIDs(repoIDs, 400)
	if len(ids) == 0 {
		return map[string]int{}, nil
	}
	query := `SELECT repo_id, COALESCE(stars, 0) AS stars
                    FROM github_repo_candidates
                    WHERE repo_id = ANY(%s)
                      AND POSITION(%s IN LOWER(full_name)) = 0`
	ctx := context.Background()
	tx, err := r.beginRead(ctx)
	if err != nil {
		return nil, fmt.Errorf("postgres: project stars transaction: %w", err)
	}
	defer func() { _ = tx.Rollback(ctx) }()
	rows, err := tx.Query(ctx, dollarPlaceholders(query), ids, "awesome")
	if err != nil {
		return nil, fmt.Errorf("postgres: project stars query: %w", err)
	}
	defer rows.Close()
	result := map[string]int{}
	for rows.Next() {
		values, err := rows.Values()
		if err != nil {
			return nil, fmt.Errorf("postgres: project stars row: %w", err)
		}
		if len(values) >= 2 {
			id, _ := values[0].(string)
			if id != "" {
				result[id] = intOrZero(values[1])
			}
		}
	}
	if err := rows.Err(); err != nil {
		return nil, fmt.Errorf("postgres: project stars rows: %w", err)
	}
	if err := tx.Commit(ctx); err != nil {
		return nil, fmt.Errorf("postgres: project stars commit: %w", err)
	}
	return result, nil
}

// 对齐 PROJECT_POPULARITY_WINDOW_DAYS / PROJECT_POPULARITY_SUSPICION_CUTOFF
// （后者即 github_heat.SUSPICION_DEMOTION_THRESHOLD）。
const (
	projectPopularityWindowDays      = 7
	projectPopularitySuspicionCutoff = 0.5
)

// GetProjectPopularityMap 逐字复刻 get_project_popularity_map：
// {repo_id: (近 7 日星增, 总星数)}，窗口含当天，刷星嫌疑达降权线的日增不计入。
func (r *ProjectSearchRepository) GetProjectPopularityMap(repoIDs []string) (map[string]projectsearch.Popularity, error) {
	ids := cleanProjectRepoIDs(repoIDs, 400)
	if len(ids) == 0 {
		return map[string]projectsearch.Popularity{}, nil
	}
	zone, err := time.LoadLocation(r.timezone)
	if err != nil {
		return nil, fmt.Errorf("postgres: scheduler timezone %q: %w", r.timezone, err)
	}
	now := time.Now().In(zone)
	today := now.Format("2006-01-02")
	windowStart := now.AddDate(0, 0, -(projectPopularityWindowDays - 1)).Format("2006-01-02")
	query := `SELECT c.repo_id,
                           COALESCE(w.weekly_star_growth, 0) AS weekly_star_growth,
                           COALESCE(c.stars, 0) AS stars
                    FROM github_repo_candidates c
                    LEFT JOIN (
                        SELECT gm.repo_id,
                               SUM(CASE WHEN COALESCE(gm.growth_suspicion_score, 0) >= %s THEN 0
                                        ELSE GREATEST(gm.daily_star_growth, 0) END) AS weekly_star_growth
                        FROM github_repo_daily_metrics gm
                        WHERE gm.repo_id = ANY(%s)
                          AND gm.metric_date BETWEEN %s AND %s
                          AND gm.daily_growth_available = TRUE
                        GROUP BY gm.repo_id
                    ) w ON w.repo_id = c.repo_id
                    WHERE c.repo_id = ANY(%s)`
	ctx := context.Background()
	tx, err := r.beginRead(ctx)
	if err != nil {
		return nil, fmt.Errorf("postgres: project popularity transaction: %w", err)
	}
	defer func() { _ = tx.Rollback(ctx) }()
	rows, err := tx.Query(ctx, dollarPlaceholders(query), projectPopularitySuspicionCutoff, ids, windowStart, today, ids)
	if err != nil {
		return nil, fmt.Errorf("postgres: project popularity query: %w", err)
	}
	defer rows.Close()
	result := map[string]projectsearch.Popularity{}
	for rows.Next() {
		values, err := rows.Values()
		if err != nil {
			return nil, fmt.Errorf("postgres: project popularity row: %w", err)
		}
		if len(values) >= 3 {
			id, _ := values[0].(string)
			if id != "" {
				result[id] = projectsearch.Popularity{WeeklyGrowth: intOrZero(values[1]), Stars: intOrZero(values[2])}
			}
		}
	}
	if err := rows.Err(); err != nil {
		return nil, fmt.Errorf("postgres: project popularity rows: %w", err)
	}
	if err := tx.Commit(ctx); err != nil {
		return nil, fmt.Errorf("postgres: project popularity commit: %w", err)
	}
	return result, nil
}

func (r *ProjectSearchRepository) ListProjects(input projectsearch.ListProjectsInput) (projectsearch.CatalogPage, error) {
	page := input.Page
	if page < 1 {
		page = 1
	}
	pageSize := clampProjectSearchLimit(input.PageSize, 24, 100)
	minStars := input.MinStars
	if minStars <= 0 {
		minStars = projectSearchMinStars
	}
	var candidates []string
	if input.CandidateRepoIDs != nil {
		candidates = cleanProjectRepoIDs(input.CandidateRepoIDs, 200)
		if len(candidates) == 0 {
			return projectsearch.CatalogPage{Items: []map[string]any{}, Total: 0}, nil
		}
	}

	zone, err := time.LoadLocation(r.timezone)
	if err != nil {
		return projectsearch.CatalogPage{}, fmt.Errorf("postgres: scheduler timezone %q: %w", r.timezone, err)
	}
	query := buildProjectListQuery(input, candidates, minStars, page, pageSize, time.Now().In(zone))
	ctx := context.Background()
	tx, err := r.beginRead(ctx)
	if err != nil {
		return projectsearch.CatalogPage{}, fmt.Errorf("postgres: project list transaction: %w", err)
	}
	defer func() { _ = tx.Rollback(ctx) }()
	var total int64
	if err := tx.QueryRow(ctx, dollarPlaceholders(query.countSQL), query.countArgs...).Scan(&total); err != nil {
		return projectsearch.CatalogPage{}, fmt.Errorf("postgres: project list count: %w", err)
	}
	rows, err := tx.Query(ctx, dollarPlaceholders(query.rowsSQL), query.rowArgs...)
	if err != nil {
		return projectsearch.CatalogPage{}, fmt.Errorf("postgres: project list query: %w", err)
	}
	items, err := projectSearchRows(rows)
	if err != nil {
		return projectsearch.CatalogPage{}, fmt.Errorf("postgres: project list rows: %w", err)
	}
	if err := tx.Commit(ctx); err != nil {
		return projectsearch.CatalogPage{}, fmt.Errorf("postgres: project list commit: %w", err)
	}
	return projectsearch.CatalogPage{Items: items, Total: int(total)}, nil
}

type projectListQuery struct {
	countSQL  string
	countArgs []any
	rowsSQL   string
	rowArgs   []any
}

// buildProjectListQuery 拼装 ListProjects 的计数/分页 SQL 与参数；%s 占位符
// 按文本序与参数一一对应，now 为调度时区下的当前时刻。
func buildProjectListQuery(input projectsearch.ListProjectsInput, candidates []string, minStars, page, pageSize int, now time.Time) projectListQuery {
	filters := []string{"COALESCE(c.stars, 0) >= %s"}
	params := []any{minStars}
	if len(candidates) > 0 {
		filters = append(filters, "c.repo_id = ANY(%s)")
		params = append(params, candidates)
	}
	if input.EnrichedOnly {
		filters = append(filters, "ge.status = 'succeeded'", ghQuarantineFilter)
	}
	if input.Scope == "today" {
		filters = append(filters, "COALESCE(gm.daily_growth_available, FALSE)", "COALESCE(gm.daily_star_growth, 0) > 0")
	} else if input.Scope == "recommended" {
		filters = append(filters, "gr.repo_id IS NOT NULL")
	}
	if input.Category != "" {
		filters = append(filters, "ge.category_slug = %s")
		params = append(params, input.Category)
	}
	if input.Subcategory != "" {
		if defaultSub, ok := ghDefaultSubcategoryByCategory[input.Category]; ok && input.Subcategory == defaultSub {
			filters = append(filters, "(ge.subcategory_slug = %s OR COALESCE(ge.subcategory_slug, '') = '')")
		} else {
			filters = append(filters, "ge.subcategory_slug = %s")
		}
		params = append(params, input.Subcategory)
	}
	if input.Language != "" {
		filters = append(filters, "LOWER(COALESCE(c.language, '')) = LOWER(%s)")
		params = append(params, input.Language)
	}
	if input.Q != "" {
		terms := projectSearchTerms(input.Q)
		if len(terms) == 0 {
			filters = append(filters, "FALSE")
		} else {
			termFilter := ghTermMatchFilter
			for _, term := range terms {
				like := "%" + escapeLikeLiteral.Replace(term) + "%"
				filters = append(filters, termFilter)
				for range len(ghTermMatchFieldsWithI18nTags) {
					params = append(params, like)
				}
			}
		}
	}

	selectColumns := append([]string{}, ghSelectColumns...)
	selectColumns = append(selectColumns, "FALSE is_favorited, NULL::timestamptz favorited_at, FALSE user_added, NULL::timestamptz user_added_at, NULL::timestamptz collection_at")
	selectColumns = append(selectColumns, ghSelectTailColumns...)

	strongThreshold := 0
	strongConditions := []string{}
	strongParams := []any{}
	terms := projectSearchTerms(input.Q)
	if input.Sort == "relevance" && input.Q != "" && candidates == nil && len(terms) > 0 {
		strongThreshold = projectSearchRelevanceStrongMatchThreshold
		for _, term := range terms {
			like := "%" + escapeLikeLiteral.Replace(term) + "%"
			strongConditions = append(strongConditions, projectSearchTermFilterForFields(projectSearchStrongTermFields))
			for range projectSearchStrongTermFields {
				strongParams = append(strongParams, like)
			}
		}
		withMarker := make([]string, 0, len(selectColumns)+1)
		withMarker = append(withMarker, selectColumns[:len(ghSelectColumns)]...)
		withMarker = append(withMarker, "(("+strings.Join(strongConditions, " AND ")+"))::boolean has_strong_match")
		withMarker = append(withMarker, selectColumns[len(ghSelectColumns):]...)
		selectColumns = withMarker
	}
	selectSQL := "SELECT " + strings.Join(selectColumns, ",") + ghSelectFrom
	dateParams := effectiveMetricDateParams(now)
	selectSQL += " " + ghMetricsJoin
	// 占位符文本序：指标 JOIN → today_top 驱动表 → WHERE 过滤，参数按同序前置。
	joinParams := append([]any{}, dateParams...)
	if input.Scope == "today" {
		status := ""
		if input.EnrichedOnly {
			status = " AND ge_top.status = 'succeeded' AND " + strings.ReplaceAll(ghQuarantineFilter, "c.", "c_top.")
		}
		selectSQL += " JOIN (SELECT c_top.repo_id FROM github_repo_candidates c_top JOIN github_repo_daily_metrics gm_top ON gm_top.repo_id=c_top.repo_id AND gm_top.metric_date=" + effectiveMetricDateSQL + " AND gm_top.daily_growth_available=TRUE AND gm_top.daily_star_growth>0 LEFT JOIN github_repo_enrichments ge_top ON ge_top.repo_id=c_top.repo_id WHERE COALESCE(c_top.stars,0)>=%s" + status + " ORDER BY gm_top.hot_score DESC NULLS LAST,gm_top.daily_star_growth DESC NULLS LAST,gm_top.stars DESC NULLS LAST,c_top.full_name ASC LIMIT 50) today_top ON today_top.repo_id=c.repo_id"
		joinParams = append(joinParams, dateParams...)
		joinParams = append(joinParams, minStars)
	}
	params = append(joinParams, params...)
	selectSQL += " WHERE " + strings.Join(filters, " AND ")

	order, orderParams := projectSearchOrder(input.Scope, input.Sort, input.Q, candidates)
	base := "WITH project_rows AS (" + selectSQL + ")"
	countSQL := base
	rowsSQL := base
	countArgs := append([]any{}, strongParams...)
	countArgs = append(countArgs, params...)
	rowArgs := append([]any{}, strongParams...)
	rowArgs = append(rowArgs, params...)
	if strongThreshold > 0 {
		base += ", counts AS (SELECT COUNT(*) AS total_all, COUNT(*) FILTER (WHERE has_strong_match) AS total_strong FROM project_rows)"
		countSQL = base + " SELECT COUNT(*) AS cnt FROM project_rows WHERE has_strong_match OR (SELECT total_strong FROM counts) < %s"
		rowsSQL = base + " SELECT * FROM project_rows WHERE has_strong_match OR (SELECT total_strong FROM counts) < %s ORDER BY " + order + " LIMIT %s OFFSET %s"
		countArgs = append(countArgs, strongThreshold)
		rowArgs = append(rowArgs, strongThreshold)
	} else {
		countSQL = base + " SELECT COUNT(*) AS cnt FROM project_rows"
		rowsSQL = base + " SELECT * FROM project_rows ORDER BY " + order + " LIMIT %s OFFSET %s"
	}
	rowArgs = append(rowArgs, orderParams...)
	rowArgs = append(rowArgs, pageSize, (page-1)*pageSize)
	return projectListQuery{countSQL: countSQL, countArgs: countArgs, rowsSQL: rowsSQL, rowArgs: rowArgs}
}

func projectSearchOrder(scope, sortName, query string, candidates []string) (string, []any) {
	if scope == "today" {
		sortName = "hot"
	}
	if sortName == "relevance" && candidates != nil {
		return "array_position(%s::text[],repo_id),full_name ASC", []any{candidates}
	}
	switch sortName {
	case "hot":
		return "hot_score DESC NULLS LAST,daily_star_growth DESC NULLS LAST,stars DESC,full_name ASC", nil
	case "updated":
		return "COALESCE(NULLIF(pushed_at,''),last_seen_at::text,first_seen_at::text) DESC NULLS LAST,stars DESC,full_name ASC", nil
	case "recent":
		anchor := collectionRecentAnchor
		if scope == "recommended" {
			anchor = "COALESCE(recommended_at," + collectionRecentAnchor + ")"
		}
		return anchor + " DESC NULLS LAST,stars DESC,full_name ASC", nil
	case "name":
		return "full_name ASC", nil
	case "relevance":
		normalized := normalizeSearchQuery(query)
		prefix := escapeLikeLiteral.Replace(normalized) + "%"
		return "CASE WHEN LOWER(full_name)=LOWER(%s) THEN 0 WHEN LOWER(split_part(full_name,'/',2))=LOWER(%s) THEN 1 WHEN LOWER(COALESCE(title,''))=LOWER(%s) THEN 2 WHEN split_part(full_name,'/',2) ILIKE %s ESCAPE '=' THEN 3 WHEN full_name ILIKE %s ESCAPE '=' THEN 4 WHEN COALESCE(title,'') ILIKE %s ESCAPE '=' THEN 5 ELSE 6 END,stars DESC,forks DESC,full_name ASC", []any{normalized, normalized, normalized, prefix, prefix, prefix}
	default:
		return "stars DESC,forks DESC,full_name ASC", nil
	}
}

func cleanProjectRepoIDs(values []string, limit int) []string {
	seen := map[string]bool{}
	out := make([]string, 0, minProjectSearchInt(len(values), limit))
	for _, value := range values {
		value = strings.TrimSpace(value)
		if value == "" || seen[value] {
			continue
		}
		seen[value] = true
		out = append(out, value)
		if len(out) >= limit {
			break
		}
	}
	return out
}

func minProjectSearchInt(a, b int) int {
	if a < b {
		return a
	}
	return b
}
