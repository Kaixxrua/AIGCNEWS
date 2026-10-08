package postgres

import (
	"aigcnews/mcp-go/internal/mcpapp"
	"reflect"
	"testing"
)

func TestDatabaseProjectMetadataSurvivesPublicProjection(t *testing.T) {
	row := normalizeProjectRow(map[string]any{
		"full_name": "explodinggradients/ragas", "tags_json": `["LLM 评测","RAG 评测"]`,
		"tags_en_json": `["LLM evaluation"]`, "topics_json": `["llm","evaluation"]`,
	})
	item := mcpapp.PublicProjectItem(row)
	expected := map[string][]any{"tags": {"LLM 评测", "RAG 评测"}, "tags_zh": {"LLM 评测", "RAG 评测"}, "tags_en": {"LLM evaluation"}, "topics": {"llm", "evaluation"}}
	for _, pair := range item {
		if want, ok := expected[pair.Key]; ok {
			if !reflect.DeepEqual(pair.Value, want) {
				t.Fatalf("%s: got %#v, want %#v", pair.Key, pair.Value, want)
			}
			delete(expected, pair.Key)
		}
	}
	if len(expected) > 0 {
		t.Fatalf("missing fields: %v", expected)
	}
}
