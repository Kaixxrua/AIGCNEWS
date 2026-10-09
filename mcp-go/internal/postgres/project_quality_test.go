package postgres

import (
	"context"
	"encoding/json"
	"os"
	"strings"
	"testing"

	"aigcnews/mcp-go/internal/mcpapp"
	"aigcnews/mcp-go/internal/projectsearch"
	"github.com/jackc/pgx/v5/pgxpool"
)

type qualityFallback struct{}

func (qualityFallback) Search(projectsearch.FallbackSearchInput) (projectsearch.FallbackSearchResult, error) {
	return projectsearch.FallbackSearchResult{Items: []map[string]any{}}, nil
}

// The Python PostgreSQL gate seeds and owns the scratch schema, then invokes
// this read-only replay. Normal Go-only runs have no database dependency.
func TestProjectQualityReplay(t *testing.T) {
	path := os.Getenv("TEST_QUALITY_INPUT")
	if path == "" {
		t.Skip("invoked by the PostgreSQL catalog quality gate")
	}
	cfg, err := pgxpool.ParseConfig(os.Getenv("TEST_POSTGRES_DSN"))
	if err != nil {
		t.Fatal("invalid test DSN")
	}
	if !strings.HasPrefix(cfg.ConnConfig.Database, "aigcnews_test") ||
		!strings.HasPrefix(cfg.ConnConfig.RuntimeParams["options"], "-c search_path=aigcnews_it_") ||
		os.Getenv("TEST_POSTGRES_RUN_ID") == "" {
		t.Fatal("requires guarded test database and owned scratch schema")
	}
	cfg.ConnConfig.RuntimeParams["default_transaction_read_only"] = "on"
	pool, err := pgxpool.NewWithConfig(context.Background(), cfg)
	if err != nil {
		t.Fatal(err)
	}
	defer pool.Close()
	var marker string
	err = pool.QueryRow(context.Background(), "SELECT run_id FROM public.aigcnews_test_run_guard WHERE run_id=$1", os.Getenv("TEST_POSTGRES_RUN_ID")).Scan(&marker)
	if err != nil {
		t.Fatal("missing test-run marker")
	}
	var cases []struct {
		ID      string
		Query   string
		Filters struct{ Language, Category, Subcategory string }
	}
	data, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	if err = json.Unmarshal(data, &cases); err != nil {
		t.Fatal(err)
	}
	engine, err := projectsearch.NewEngine(NewProjectSearchRepository(pool, "Asia/Shanghai"),
		qualityFallback{}, nil, nil, projectsearch.EngineConfig{Strategy: "v2", SemanticHeatFirst: true, AdoptionWeight: 0.006})
	if err != nil {
		t.Fatal(err)
	}
	observed := map[string][]string{}
	for _, c := range cases {
		result, err := engine.SearchProjects(mcpapp.ProjectSearchInput{
			Query: c.Query, Mode: "ai", Language: c.Filters.Language, Category: c.Filters.Category,
			Subcategory: c.Filters.Subcategory, Scope: "all", Page: 1, Limit: 10,
		})
		if err != nil {
			t.Fatalf("%s: %v", c.ID, err)
		}
		data, err = json.Marshal(result)
		if err != nil {
			t.Fatal(err)
		}
		var response struct {
			Items []struct {
				Name string `json:"full_name"`
			}
		}
		if err = json.Unmarshal(data, &response); err != nil {
			t.Fatal(err)
		}
		names := []string{}
		for _, item := range response.Items {
			names = append(names, item.Name)
		}
		observed[c.ID] = names
	}
	data, err = json.Marshal(observed)
	if err != nil {
		t.Fatal(err)
	}
	if err = os.WriteFile(os.Getenv("TEST_QUALITY_OUTPUT"), data, 0600); err != nil {
		t.Fatal(err)
	}
}
