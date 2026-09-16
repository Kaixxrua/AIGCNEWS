package mcpapp

import (
	"crypto/sha256"
	"encoding/hex"
	"testing"
)

func TestUIExplicitLargeOriginalFileIsComplete(t *testing.T) {
	app := uiApp(t)
	initial := uiCall(t, app, "get_ui_template", map[string]any{"id": "tweakcn-claude"})["structuredContent"].(map[string]any)
	omitted := initial["omitted_files"].([]any)
	if len(omitted) == 0 {
		t.Fatal("large original should require explicit file retrieval")
	}
	content := ""
	offset := 0
	hashText := ""
	for {
		envelope := uiCall(t, app, "get_ui_template", map[string]any{"id": "tweakcn-claude", "file": "utils/theme-presets.ts", "file_offset": offset})
		data := envelope["structuredContent"].(map[string]any)
		if data["truncated"] == true || envelope["isError"] != false {
			t.Fatal("paged source failed")
		}
		next := -1
		for _, raw := range data["files"].([]any) {
			file := raw.(map[string]any)
			if file["name"] != "utils/theme-presets.ts" {
				if file["content"] != nil {
					t.Fatal("unrelated content included")
				}
				continue
			}
			content += file["content"].(string)
			hashText = file["sha256"].(string)
			if file["next_offset"] != nil {
				next = int(file["next_offset"].(float64))
				if next <= offset {
					t.Fatal("cursor did not advance")
				}
			}
		}
		if next < 0 {
			break
		}
		offset = next
	}
	hash := sha256.Sum256([]byte(content))
	if len(content) <= 60000 || hex.EncodeToString(hash[:]) != hashText {
		t.Fatal("original file was truncated")
	}
	for _, args := range []map[string]any{{"id": "tweakcn-claude", "file_offset": 1}, {"id": "tweakcn-claude", "file": "utils/theme-presets.ts", "file_offset": -1}, {"id": "tweakcn-claude", "file": "utils/theme-presets.ts", "file_offset": 262144}} {
		if uiCall(t, app, "get_ui_template", args)["isError"] != true {
			t.Fatal("invalid offset accepted")
		}
	}

}

func TestUIThemeAndTemplateFiltersAreAdditive(t *testing.T) {
	app := uiApp(t)
	for _, query := range []string{"配色", "palette"} {
		result := uiCall(t, app, "search_ui_templates", map[string]any{"q": query, "kind": "theme", "framework": "css"})
		if result["isError"] != false {
			t.Fatalf("theme search failed: %v", result)
		}
		data := result["structuredContent"].(map[string]any)
		if data["total"] != float64(42) {
			t.Fatalf("theme count: %v", data["total"])
		}
		for _, raw := range data["items"].([]any) {
			item := raw.(map[string]any)
			if item["kind"] != "theme" || item["subcategory"] != "color-theme" {
				t.Fatalf("wrong theme result: %v", item)
			}
		}
	}
	// Pin the fixture query so importing another dashboard does not break this contract.
	result := uiCall(t, app, "search_ui_templates", map[string]any{"kind": "template", "category": "dashboard", "q": "shadcn"})
	data := result["structuredContent"].(map[string]any)
	if data["total"] != float64(1) {
		t.Fatalf("dashboard count: %v", data)
	}
	if uiCall(t, app, "search_ui_templates", map[string]any{"kind": "unreviewed"})["isError"] != true {
		t.Fatal("unknown kind accepted")
	}
}
