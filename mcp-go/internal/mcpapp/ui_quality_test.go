package mcpapp

import (
	"crypto/sha256"
	"encoding/hex"
	"strings"
	"testing"

	"aigcnews/mcp-go/internal/uicatalog"
)

func TestUIExplicitLargeOriginalFileIsComplete(t *testing.T) {
	original := strings.Repeat("源码🙂", 30000)
	content := ""
	offset := 0
	for {
		page, rawNext, total, err := uiSourcePage(original, offset)
		if err != nil || total != len([]rune(original)) {
			t.Fatalf("paged source failed: total=%d err=%v", total, err)
		}
		content += page
		if rawNext == nil {
			break
		}
		next := rawNext.(int)
		if next <= offset {
			t.Fatal("cursor did not advance")
		}
		offset = next
	}
	wantHash := sha256.Sum256([]byte(original))
	gotHash := sha256.Sum256([]byte(content))
	if len(content) <= 60000 || hex.EncodeToString(gotHash[:]) != hex.EncodeToString(wantHash[:]) {
		t.Fatal("original file was truncated")
	}

	app := uiApp(t)
	catalog, err := uicatalog.New()
	if err != nil {
		t.Fatal(err)
	}
	sample := catalog.Search("", "", "")[0]
	filename := sample.Files[0].Name
	for _, args := range []map[string]any{{"id": sample.ID, "file_offset": 1}, {"id": sample.ID, "file": filename, "file_offset": -1}, {"id": sample.ID, "file": filename, "file_offset": 262144}} {
		if uiCall(t, app, "get_ui_template", args)["isError"] != true {
			t.Fatal("invalid offset accepted")
		}
	}
}

func TestUIKindCategoryAndFrameworkFiltersAreAdditive(t *testing.T) {
	app := uiApp(t)
	for _, query := range []string{"按钮", "button"} {
		result := uiCall(t, app, "search_ui_templates", map[string]any{"q": query, "kind": "component", "category": "component", "framework": "html"})
		if result["isError"] != false {
			t.Fatalf("filtered search failed: %v", result)
		}
		data := result["structuredContent"].(map[string]any)
		if data["total"] != float64(1) {
			t.Fatalf("filtered count: %v", data["total"])
		}
		for _, raw := range data["items"].([]any) {
			item := raw.(map[string]any)
			if item["kind"] != "component" || item["subcategory"] != "inputs" {
				t.Fatalf("wrong filtered result: %v", item)
			}
		}
	}
	if uiCall(t, app, "search_ui_templates", map[string]any{"kind": "unreviewed"})["isError"] != true {
		t.Fatal("unknown kind accepted")
	}
}
