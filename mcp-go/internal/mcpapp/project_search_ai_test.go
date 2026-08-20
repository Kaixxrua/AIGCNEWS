package mcpapp

import (
	"errors"
	"testing"

	"aigcnews/mcp-go/internal/jsonx"
	"aigcnews/mcp-go/internal/projectsem"
)

type aiProjectSearchEngineStub struct {
	input  ProjectSearchInput
	result jsonx.Object
	err    error
}

func (s *aiProjectSearchEngineStub) SearchProjects(input ProjectSearchInput) (jsonx.Object, error) {
	s.input = input
	if s.err != nil {
		return nil, s.err
	}
	return s.result, nil
}

func TestValidateSearchGitHubAIProjectsDefaultsAndTaxonomy(t *testing.T) {
	input, err := validateSearchGitHubAIProjectsArgs(map[string]any{
		"q": "  rag  ", "subcategory": "vector_search",
	})
	if err != nil {
		t.Fatalf("validateSearchGitHubAIProjectsArgs() error = %v", err)
	}
	if input.q != "rag" || input.category != "rag_knowledge" || input.scope != "all" ||
		input.lang != "zh" || input.sort != "" || input.page != 1 || input.limit != 10 {
		t.Fatalf("validated input = %+v", input)
	}
}

func TestValidateSearchGitHubAIProjectsErrors(t *testing.T) {
	cases := []struct {
		name string
		args map[string]any
		want string
	}{
		{
			name: "nested required and literal",
			args: map[string]any{"intent": map[string]any{}},
			want: "intent.schema_version: Field required; intent.language: Field required; intent.lexical_terms: Field required; intent.semantic_queries: Field required",
		},
		{
			name: "nested item",
			args: map[string]any{
				"intent": map[string]any{
					"schema_version":   projectIntentSchemaVersion,
					"language":         "en",
					"lexical_terms":    []any{""},
					"semantic_queries": []any{"rag"},
				},
			},
			want: "intent.lexical_terms.0: String should have at least 1 character",
		},
		{
			name: "nested semantic protected token",
			args: map[string]any{
				"q": "rag toolkit",
				"intent": map[string]any{
					"schema_version":   projectIntentSchemaVersion,
					"language":         "en",
					"lexical_terms":    []any{"toolkit"},
					"semantic_queries": []any{"toolkit"},
				},
			},
			want: ": Value error, client intent must preserve protected technical tokens from q",
		},
		{
			name: "outer taxonomy",
			args: map[string]any{"category": "not-a-category"},
			want: ": Value error, category must be a valid AIGC_NEWS category slug",
		},
		{
			name: "category child mismatch",
			args: map[string]any{"category": "rag_knowledge", "subcategory": "code_generation"},
			want: ": Value error, subcategory must belong to category",
		},
		{
			name: "scope literal",
			args: map[string]any{"scope": "weekly"},
			want: "scope: Input should be 'all', 'today' or 'recommended'",
		},
		{
			name: "extras",
			args: map[string]any{"z": true, "a": true},
			want: "a: Extra inputs are not permitted; z: Extra inputs are not permitted",
		},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			_, err := validateSearchGitHubAIProjectsArgs(tc.args)
			if err == nil {
				t.Fatal("validation unexpectedly succeeded")
			}
			inputErr, ok := err.(ToolInputError)
			if !ok {
				t.Fatalf("error type = %T, want ToolInputError", err)
			}
			if inputErr.Message != tc.want {
				t.Fatalf("message = %q, want %q", inputErr.Message, tc.want)
			}
		})
	}
}

func TestProjectSearchServiceSearchMapsAIInputAndFinalizes(t *testing.T) {
	engine := &aiProjectSearchEngineStub{result: jsonx.Object{
		{Key: "items", Value: []any{jsonx.Object{
			{Key: "full_name", Value: "acme/rag"},
			{Key: "description", Value: "检索工具"},
			{Key: "description_en", Value: "RAG toolkit"},
			{Key: "description_zh", Value: "检索工具"},
		}}},
		{Key: "total", Value: 1},
	}}
	service := NewProjectSearchService(engine, "https://radar.example.com")
	got, err := service.Search(map[string]any{
		"q":        "rag",
		"category": "rag_knowledge",
		"scope":    "today",
		"sort":     "hot",
		"lang":     "en",
	})
	if err != nil {
		t.Fatalf("Search() error = %v", err)
	}
	want := `{"items":[{"full_name":"acme/rag","description":"RAG toolkit","description_en":"RAG toolkit","detail_url":"https://radar.example.com/projects?q=acme%2Frag&utm_source=mcp&utm_medium=tool","data_source":"aigcnews.cn"}],"total":1,"lang":"en","attribution":"Data provided by AIGC Radar · https://radar.example.com"}`
	if encoded := string(jsonx.MustMarshalCompact(got)); encoded != want {
		t.Fatalf("response = %s, want %s", encoded, want)
	}
	if engine.input.Mode != "ai" || engine.input.Query != "rag" || engine.input.Category != "rag_knowledge" ||
		engine.input.Scope != "today" || engine.input.Sort != "hot" || engine.input.Language != "" ||
		engine.input.Page != 1 || engine.input.Limit != 10 {
		t.Fatalf("engine input = %+v", engine.input)
	}
}

func TestProjectSearchServiceSearchClientIntent(t *testing.T) {
	engine := &aiProjectSearchEngineStub{result: jsonx.Object{}}
	service := NewProjectSearchService(engine, "")
	_, err := service.Search(map[string]any{
		"q": "rag toolkit",
		"intent": map[string]any{
			"schema_version":   projectIntentSchemaVersion,
			"language":         "en",
			"intent_class":     "general_discovery",
			"lexical_terms":    []any{"rag", "toolkit"},
			"semantic_queries": []any{"rag toolkit"},
		},
	})
	if err != nil {
		t.Fatalf("Search() error = %v", err)
	}
	if engine.input.ClientIntent == nil || engine.input.ClientIntent.Language != "en" ||
		len(engine.input.ClientIntent.LexicalTerms) != 2 || engine.input.ClientIntent.LexicalTerms[0] != "rag" {
		t.Fatalf("engine client intent = %+v", engine.input.ClientIntent)
	}
	if _, err := projectsem.BuildClientProjectSearchIntent(engine.input.Query, *engine.input.ClientIntent); err != nil {
		t.Fatalf("engine client intent rejected by builder: %v", err)
	}
}

func TestProjectSearchServiceSearchPassesEngineError(t *testing.T) {
	boom := errors.New("catalog unavailable")
	engine := &aiProjectSearchEngineStub{err: boom}
	service := NewProjectSearchService(engine, "")
	_, err := service.Search(map[string]any{"q": "rag"})
	if !errors.Is(err, boom) {
		t.Fatalf("error = %v, want %v", err, boom)
	}
}
