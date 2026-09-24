package projectsearch

import (
	"testing"

	"aigcnews/mcp-go/internal/jsonx"
	"aigcnews/mcp-go/internal/mcpapp"
	"aigcnews/mcp-go/internal/projectsem"
)

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
