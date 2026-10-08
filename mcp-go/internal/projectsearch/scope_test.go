package projectsearch

import (
	"aigcnews/mcp-go/internal/mcpapp"
	"aigcnews/mcp-go/internal/projectsem"
	"testing"
)

type scopedCatalog struct {
	engineCatalogStub
	scope string
}

func (c *scopedCatalog) FindLexicalCandidateRepoIDs(in LexicalCandidateSearchInput) ([]string, error) {
	c.scope = in.Scope
	return []string{"owner/featured"}, nil
}
func (c *scopedCatalog) FindLexicalCandidateLanes(in LexicalLaneSearchInput) (projectsem.LexicalCandidateLanes, error) {
	c.scope = in.Scope
	return projectsem.LexicalCandidateLanes{Strict: []LexicalCandidate{{RepoID: "owner/featured", TermCoverage: 1}}}, nil
}
func (c *scopedCatalog) ListProjects(in ListProjectsInput) (CatalogPage, error) {
	if c.scope != in.Scope {
		return CatalogPage{}, nil
	}
	return CatalogPage{Items: []map[string]any{{"full_name": "owner/featured"}}, Total: 1}, nil
}
func TestRecommendedScopeReachesBothCandidateStrategies(t *testing.T) {
	for _, strategy := range []string{"legacy", "v2"} {
		c := &scopedCatalog{}
		e, err := NewEngine(c, nil, nil, nil, EngineConfig{Strategy: strategy})
		if err != nil {
			t.Fatal(err)
		}
		result, err := e.SearchProjects(mcpapp.ProjectSearchInput{Query: "agent", Mode: "ai", Scope: "recommended"})
		if err != nil || c.scope != "recommended" || resultValue(result, "total") != 1 {
			t.Fatalf("%s: scope=%q result=%v error=%v", strategy, c.scope, result, err)
		}
	}
}
