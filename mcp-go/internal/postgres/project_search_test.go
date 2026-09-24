package postgres

import (
	"fmt"
	"reflect"
	"strings"
	"testing"
	"time"

	"github.com/jackc/pgx/v5/pgxpool"

	"aigcnews/mcp-go/internal/projectsearch"
)

func TestNewProjectSearchRepositoryStatementTimeoutCompatibility(t *testing.T) {
	pool := (*pgxpool.Pool)(nil)

	legacy := NewProjectSearchRepository(pool, "")
	if legacy.timezone != "Asia/Shanghai" {
		t.Fatalf("legacy constructor timezone = %q, want Asia/Shanghai", legacy.timezone)
	}
	if legacy.statementTimeoutMillis != 0 {
		t.Fatalf("legacy constructor timeout = %d, want 0", legacy.statementTimeoutMillis)
	}

	configured := NewProjectSearchRepository(pool, "UTC", 9000)
	if configured.timezone != "UTC" {
		t.Fatalf("configured constructor timezone = %q, want UTC", configured.timezone)
	}
	if configured.statementTimeoutMillis != 9000 {
		t.Fatalf("configured constructor timeout = %d, want 9000", configured.statementTimeoutMillis)
	}

	clamped := NewProjectSearchRepository(pool, "UTC", 0)
	if clamped.statementTimeoutMillis != 1 {
		t.Fatalf("non-positive configured timeout = %d, want 1", clamped.statementTimeoutMillis)
	}
}

func TestEffectiveMetricDateMirrorsPythonCatalog(t *testing.T) {
	// 与 postgres_project_catalog._EFFECTIVE_METRIC_DATE_SQL 逐字一致
	const python = "(SELECT COALESCE(MAX(md.metric_date),%s) FROM github_repo_daily_metrics md" +
		" WHERE md.metric_date BETWEEN %s AND %s)"
	if effectiveMetricDateSQL != python {
		t.Fatalf("effectiveMetricDateSQL = %q", effectiveMetricDateSQL)
	}
	if !strings.HasSuffix(ghMetricsJoin, "gm.metric_date = "+python) {
		t.Fatalf("ghMetricsJoin = %q", ghMetricsJoin)
	}
	zone, err := time.LoadLocation("Asia/Shanghai")
	if err != nil {
		t.Fatal(err)
	}
	got := effectiveMetricDateParams(time.Date(2026, 3, 1, 0, 30, 0, 0, zone))
	want := []any{"2026-03-01", "2026-02-28", "2026-03-01"}
	if !reflect.DeepEqual(got, want) {
		t.Fatalf("params = %v, want %v", got, want)
	}
}

// inlineProjectListArgs 按文本序把参数代入 %s 占位符，占位符与参数数量
// 不一致时直接判失败——pgx 按位置绑定，错位只会在运行期报编码错误。
func inlineProjectListArgs(t *testing.T, sql string, args []any) string {
	t.Helper()
	parts := strings.Split(sql, "%s")
	if len(parts)-1 != len(args) {
		t.Fatalf("placeholders = %d, args = %d", len(parts)-1, len(args))
	}
	var out strings.Builder
	for i, part := range parts {
		out.WriteString(part)
		if i == len(args) {
			break
		}
		switch value := args[i].(type) {
		case string:
			out.WriteString("'" + value + "'")
		case []string:
			out.WriteString("ARRAY['" + strings.Join(value, "','") + "']")
		default:
			out.WriteString(fmt.Sprint(value))
		}
	}
	return out.String()
}

func TestProjectListTodayScopeBindsParamsInTextOrder(t *testing.T) {
	now := time.Date(2026, 3, 1, 1, 30, 0, 0, time.UTC)
	effective := "(SELECT COALESCE(MAX(md.metric_date),'2026-03-01') FROM github_repo_daily_metrics md WHERE md.metric_date BETWEEN '2026-02-28' AND '2026-03-01')"
	for _, tc := range []struct {
		name       string
		candidates []string
		sort       string
	}{
		{name: "browse", sort: "hot"},
		{name: "semantic candidates", candidates: []string{"owner/a", "owner/b"}, sort: "relevance"},
	} {
		t.Run(tc.name, func(t *testing.T) {
			input := projectsearch.ListProjectsInput{
				Scope: "today", Category: "agents", Language: "Python", Sort: tc.sort,
				EnrichedOnly: true, CandidateRepoIDs: tc.candidates,
			}
			query := buildProjectListQuery(input, tc.candidates, 500, 2, 10, now)
			count := inlineProjectListArgs(t, query.countSQL, query.countArgs)
			rows := inlineProjectListArgs(t, query.rowsSQL, query.rowArgs)
			for _, sql := range []string{count, rows} {
				for _, want := range []string{
					"gm.metric_date = " + effective,
					"gm_top.metric_date=" + effective,
					"WHERE COALESCE(c_top.stars,0)>=500 AND ge_top.status = 'succeeded'",
					"WHERE COALESCE(c.stars, 0) >= 500",
					"ge.category_slug = 'agents'",
					"LOWER(COALESCE(c.language, '')) = LOWER('Python')",
				} {
					if !strings.Contains(sql, want) {
						t.Fatalf("SQL missing %q:\n%s", want, sql)
					}
				}
				if tc.candidates != nil && !strings.Contains(sql, "c.repo_id = ANY(ARRAY['owner/a','owner/b'])") {
					t.Fatalf("SQL missing candidate filter:\n%s", sql)
				}
			}
			if !strings.HasSuffix(rows, "LIMIT 10 OFFSET 10") {
				t.Fatalf("rows SQL tail = %q", rows[len(rows)-40:])
			}
		})
	}
}
