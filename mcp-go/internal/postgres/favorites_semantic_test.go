package postgres

// 收藏语义通道（Go 独有，无 Python 参照）：语义命中以 OR 放宽关键词过滤，
// 其余过滤、排序与分页参数原样保留；无语义命中时 SQL 与参数不变。

import (
	"fmt"
	"reflect"
	"regexp"
	"strconv"
	"strings"
	"testing"

	"aigcnews/mcp-go/internal/mcpapp"
)

var sqlPlaceholder = regexp.MustCompile(`\$(\d+)`)

func maxPlaceholder(t *testing.T, sql string) int {
	t.Helper()
	highest := 0
	for _, match := range sqlPlaceholder.FindAllStringSubmatch(sql, -1) {
		n, err := strconv.Atoi(match[1])
		if err != nil {
			t.Fatalf("placeholder %q: %v", match[0], err)
		}
		highest = max(highest, n)
	}
	return highest
}

func indexOfRepoIDs(params []any) int {
	for i, param := range params {
		if _, ok := param.([]string); ok {
			return i
		}
	}
	return -1
}

func TestProjectCollectionQueriesSemanticLaneWidensKeywordFilter(t *testing.T) {
	dates := []any{"2026-09-30", "2026-09-29", "2026-09-30"}
	ids := []string{"acme/agent-memory", "R_kgDOSL4dpw"}
	lexical := mcpapp.ProjectCollectionFilters{UserID: 7, Q: "agent memory", Category: "agents", Tag: "rag", Sort: "stars"}
	semantic := lexical
	semantic.SemanticRepoIDs = ids

	baseCount, baseRows, baseParams, baseRowsParams := projectCollectionQueries(lexical, dates, 2, 10)
	count, rows, params, rowsParams := projectCollectionQueries(semantic, dates, 2, 10)

	at := indexOfRepoIDs(params)
	if at < 0 || !reflect.DeepEqual(params[at], ids) {
		t.Fatalf("semantic repo ids missing from params: %v", params)
	}
	// 命中清单插在关键词参数之后、tag 参数之前，其余参数序不变。
	if !reflect.DeepEqual(params[:at], baseParams[:at]) || !reflect.DeepEqual(params[at+1:], baseParams[at:]) {
		t.Fatalf("params = %v, want lexical params %v with ids inserted at %d", params, baseParams, at)
	}
	if params[at+1] != `%"rag"%` {
		t.Fatalf("tag param after ids = %v, want %%\"rag\"%%", params[at+1])
	}
	if got := rowsParams[len(rowsParams)-2:]; !reflect.DeepEqual(got, baseRowsParams[len(baseRowsParams)-2:]) || got[0] != 10 || got[1] != 10 {
		t.Fatalf("paging params = %v", got)
	}
	if maxPlaceholder(t, count) != len(params) || maxPlaceholder(t, rows) != len(rowsParams) {
		t.Fatalf("placeholders count=%d rows=%d, params=%d rowsParams=%d",
			maxPlaceholder(t, count), maxPlaceholder(t, rows), len(params), len(rowsParams))
	}
	anyClause := fmt.Sprintf(") OR c.repo_id = ANY($%d))", at+1)
	if !strings.Contains(count, anyClause) || !strings.Contains(rows, anyClause) {
		t.Fatalf("semantic OR clause %q missing:\n%s", anyClause, count)
	}
	// 排序与其余过滤（tag、分类、关键词 ILIKE）原样保留。
	orderBy := func(sql string) string {
		return sql[strings.LastIndex(sql, " ORDER BY "):strings.LastIndex(sql, " LIMIT ")]
	}
	if orderBy(rows) != orderBy(baseRows) || strings.Count(rows, " ILIKE ") != strings.Count(baseRows, " ILIKE ") {
		t.Fatalf("semantic lane changed the rest of the query:\n%s\nvs\n%s", rows, baseRows)
	}
	if strings.Contains(baseCount, "ANY(") || strings.Contains(baseRows, "ANY(") {
		t.Fatalf("lexical-only query gained a semantic clause:\n%s", baseCount)
	}
}

func TestProjectCollectionQueriesSemanticLaneEdgeCases(t *testing.T) {
	dates := []any{"2026-09-30", "2026-09-29", "2026-09-30"}
	ids := []string{"acme/x"}

	// 只有符号、分词为空：关键词侧恒假，语义命中仍可召回。
	punct := mcpapp.ProjectCollectionFilters{UserID: 7, Q: "!!!", SemanticRepoIDs: ids}
	count, _, params, _ := projectCollectionQueries(punct, dates, 1, 10)
	want := fmt.Sprintf("((FALSE) OR c.repo_id = ANY($%d))", len(params))
	if !strings.Contains(count, want) || !reflect.DeepEqual(params[len(params)-1], ids) {
		t.Fatalf("empty-terms semantic clause missing %q:\n%s\nparams=%v", want, count, params)
	}

	// 没有 q 时语义清单不参与（Get 也不会为空查询跑语义通道）。
	noQuery := mcpapp.ProjectCollectionFilters{UserID: 7, Category: "agents"}
	withIDs := noQuery
	withIDs.SemanticRepoIDs = ids
	a1, a2, a3, a4 := projectCollectionQueries(noQuery, dates, 1, 10)
	b1, b2, b3, b4 := projectCollectionQueries(withIDs, dates, 1, 10)
	if a1 != b1 || a2 != b2 || !reflect.DeepEqual(a3, b3) || !reflect.DeepEqual(a4, b4) {
		t.Fatalf("semantic ids without q changed the query")
	}
}

func TestListFavoriteRepoIDsSQLIsScopedToUserGitHubFavorites(t *testing.T) {
	for _, fragment := range []string{
		"FROM project_favorites",
		"user_id = $1",
		"project_source = 'github'",
		"ORDER BY created_at DESC, id DESC",
		"LIMIT $2",
	} {
		if !strings.Contains(listFavoriteRepoIDsSQL, fragment) {
			t.Errorf("listFavoriteRepoIDsSQL missing %q: %s", fragment, listFavoriteRepoIDsSQL)
		}
	}
	ids, err := (ProjectCollectionsRepository{}).ListFavoriteRepoIDs(0, 10)
	if err != nil || len(ids) != 0 {
		t.Fatalf("anonymous user = %v, %v; want empty without touching the pool", ids, err)
	}
	ids, err = (ProjectCollectionsRepository{}).ListFavoriteRepoIDs(7, 0)
	if err != nil || len(ids) != 0 {
		t.Fatalf("zero limit = %v, %v; want empty without touching the pool", ids, err)
	}
}
