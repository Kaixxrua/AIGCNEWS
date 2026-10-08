package projectsearch

import (
	"aigcnews/mcp-go/internal/mcpapp"
	"aigcnews/mcp-go/internal/projectsem"
	"testing"
)

type retainedCatalog struct {
	engineCatalogStub
	listed ListProjectsInput
}

func (*retainedCatalog) FindLexicalCandidateLanes(LexicalLaneSearchInput) (projectsem.LexicalCandidateLanes, error) {
	return projectsem.LexicalCandidateLanes{Relaxed: []LexicalCandidate{{RepoID: "owner/local", TermCoverage: 1}}}, nil
}
func (c *retainedCatalog) ListProjects(in ListProjectsInput) (CatalogPage, error) {
	c.listed = in
	if len(in.CandidateRepoIDs) == 0 {
		return CatalogPage{}, nil
	}
	return CatalogPage{Items: []map[string]any{{"full_name": "owner/local"}}, Total: 1}, nil
}

type returnedErrorFallback struct{ message string }

func (f returnedErrorFallback) Search(FallbackSearchInput) (FallbackSearchResult, error) {
	return FallbackSearchResult{Error: f.message}, nil
}

func TestReturnedFallbackErrorsKeepLocalMatches(t *testing.T) {
	for _, message := range []string{"HTTP 403", "HTTP 429", "GitHub fallback is disabled."} {
		e, err := NewEngine(&retainedCatalog{}, returnedErrorFallback{message}, nil, nil, EngineConfig{Strategy: "v2"})
		if err != nil {
			t.Fatal(err)
		}
		out, err := e.SearchProjects(mcpapp.ProjectSearchInput{Query: "windows screenshot", Mode: "generic"})
		if err != nil {
			t.Fatal(err)
		}
		if resultValue(out, "total") != 1 || resultValue(out, "local_total") != 1 || resultValue(out, "fallback_error") != message || resultValue(out, "result_origin") != "aigc_news_local" {
			t.Fatalf("lost local result: %v", out)
		}
		if items := resultValue(out, "items").([]any); len(items) != 1 {
			t.Fatalf("lost items: %v", items)
		}
	}
}

func TestSemanticRetryPreservesExplicitSort(t *testing.T) {
	for _, sortName := range []string{"stars", "updated", "recent", "name", "hot"} {
		c := &retainedCatalog{}
		e, err := NewEngine(c, nil, qualitySemanticStub{}, nil, EngineConfig{Strategy: "v2", SemanticEnabled: true})
		if err != nil {
			t.Fatal(err)
		}
		out, err := e.SearchProjects(mcpapp.ProjectSearchInput{Query: "agent memory", Mode: "ai", Sort: sortName})
		if err != nil || resultValue(out, "total") != 1 || resultValue(out, "sort") != sortName || c.listed.Sort != sortName {
			t.Fatalf("sort=%s hydration=%+v result=%v err=%v", sortName, c.listed, out, err)
		}
	}
}
