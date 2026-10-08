package projectsearch

import (
	"fmt"
	"reflect"
	"testing"

	"aigcnews/mcp-go/internal/jsonx"
	"aigcnews/mcp-go/internal/mcpapp"
	"aigcnews/mcp-go/internal/projectsem"
)

type qualityCatalogStub struct {
	engineCatalogStub
	listed ListProjectsInput
}

func (*qualityCatalogStub) FindLexicalCandidateLanes(LexicalLaneSearchInput) (projectsem.LexicalCandidateLanes, error) {
	lanes := projectsem.LexicalCandidateLanes{
		Relaxed: []LexicalCandidate{{RepoID: "owner/viral", TermCoverage: 1}},
	}
	for i := 0; i < 11; i++ {
		lanes.Strict = append(lanes.Strict, LexicalCandidate{RepoID: fmt.Sprintf("owner/fit-%d", i), TermCoverage: 2})
	}
	return lanes, nil
}
func (*qualityCatalogStub) GetProjectPopularityMap([]string) (map[string]Popularity, error) {
	return map[string]Popularity{"owner/viral": {Stars: 1_000_000, WeeklyGrowth: 20_000}}, nil
}
func (c *qualityCatalogStub) ListProjects(input ListProjectsInput) (CatalogPage, error) {
	c.listed = input
	return CatalogPage{Total: len(input.CandidateRepoIDs)}, nil
}

type qualitySemanticStub struct{}

func (qualitySemanticStub) SearchRepoIDs([]string) ([]SemanticHit, error) {
	return []SemanticHit{{RepoID: "owner/viral"}}, nil
}

func TestV2SearchPreservesStrictMatchesAcrossPageSizes(t *testing.T) {
	want := []string{}
	for i := 0; i < 11; i++ {
		want = append(want, fmt.Sprintf("owner/fit-%d", i))
	}
	want = append(want, "owner/viral")
	for _, limit := range []int{3, 5, 10, 20} {
		t.Run(fmt.Sprint(limit), func(t *testing.T) {
			catalog := &qualityCatalogStub{}
			engine, err := NewEngine(catalog, nil, qualitySemanticStub{}, nil, EngineConfig{
				Strategy: "v2", SemanticEnabled: true, SemanticHeatFirst: true,
			})
			if err != nil {
				t.Fatal(err)
			}
			_, err = engine.SearchProjects(mcpapp.ProjectSearchInput{
				Query: "RAG evaluation", Mode: "generic", Page: 1, Limit: limit,
			})
			if err != nil {
				t.Fatal(err)
			}
			if !reflect.DeepEqual(catalog.listed.CandidateRepoIDs, want) || catalog.listed.PageSize != limit {
				t.Fatalf("hydration = %#v, want stable order %v and page size %d", catalog.listed, want, limit)
			}
		})
	}
}

type engineCatalogStub struct{}

func (engineCatalogStub) FindLexicalCandidateRepoIDs(LexicalCandidateSearchInput) ([]string, error) {
	return nil, nil
}
func (engineCatalogStub) FindLexicalCandidateLanes(LexicalLaneSearchInput) (projectsem.LexicalCandidateLanes, error) {
	return projectsem.LexicalCandidateLanes{}, nil
}
func (engineCatalogStub) FindRepoIDsByNameSegment(string, int) ([]string, error) {
	return nil, nil
}
func (engineCatalogStub) GetProjectStarsMap([]string) (map[string]int, error) {
	return nil, nil
}
func (engineCatalogStub) GetProjectPopularityMap([]string) (map[string]Popularity, error) {
	return nil, nil
}
func (engineCatalogStub) ListProjects(ListProjectsInput) (CatalogPage, error) {
	return CatalogPage{}, nil
}

func TestNewEngineAllowsShadowStrategy(t *testing.T) {
	engine, err := NewEngine(engineCatalogStub{}, nil, nil, nil, EngineConfig{Strategy: "shadow"})
	if err != nil {
		t.Fatalf("NewEngine(shadow) error = %v", err)
	}
	if engine.cfg.Strategy != "shadow" {
		t.Fatalf("resolved strategy = %q, want shadow", engine.cfg.Strategy)
	}
}

func TestShadowStrategyUsesLegacyPathWithoutSemanticDependencies(t *testing.T) {
	engine, err := NewEngine(engineCatalogStub{}, nil, nil, nil, EngineConfig{Strategy: "shadow"})
	if err != nil {
		t.Fatalf("NewEngine(shadow) error = %v", err)
	}
	result, err := engine.SearchProjects(mcpapp.ProjectSearchInput{
		Query: "rag",
		Mode:  "generic",
		Page:  1,
		Limit: 10,
	})
	if err != nil {
		t.Fatalf("SearchProjects(shadow) error = %v", err)
	}
	if got := resultValue(result, "search_mode"); got != "generic" {
		t.Fatalf("search_mode = %v, want generic", got)
	}
}

func resultValue(result jsonx.Object, key string) any {
	for _, pair := range result {
		if pair.Key == key {
			return pair.Value
		}
	}
	return nil
}
